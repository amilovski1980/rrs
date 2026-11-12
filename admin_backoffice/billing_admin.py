"""Facturation des abonnés, réservée au personnel. Aucun secret Stripe n'est affiché."""
from django import forms
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import DetailView, ListView, TemplateView

from accounts.models import User
from billing.models import Plan, Subscription, SubscriptionInvoice
from billing.receipts import record_invoice_receipt
from billing.services import apply_subscription_object
from billing.stripe_api import StripeError, StripeNotConfigured, list_invoices, retrieve_subscription
from companies.models import Company

from .audit import journaliser
from .forms import _style_fields
from .views import AdminStaffMixin

ATTENTION_STATUS = ("past_due", "unpaid")


class BillingNoteForm(forms.Form):
    follow_up = forms.ChoiceField(label="Suivi", required=False, choices=Subscription.FOLLOW_UP)
    staff_note = forms.CharField(
        label="Note interne",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Visible uniquement dans le back-office. N'y collez pas de clé Stripe.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_fields(self)


class InvoiceNoteForm(forms.Form):
    staff_note = forms.CharField(
        label="Note interne",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_fields(self)


def _safe_stripe_message(exc: Exception) -> str:
    text = " ".join(str(getattr(exc, "message", "") or exc).split())
    lowered = text.lower()
    if any(marker in lowered for marker in ("sk_live", "sk_test", "whsec_", "rk_live", "rk_test")):
        return "Stripe a refusé l'opération. Le détail technique a été masqué."
    return (text or "Stripe n'a pas répondu.")[:180]


def _dossier(user):
    subscriptions = list(
        Subscription.objects.filter(user=user).select_related("plan").order_by("-created_at")
    )
    invoices = list(
        SubscriptionInvoice.objects.filter(user=user).select_related("subscription", "subscription__plan")
    )
    companies = list(user.companies.all().order_by("denomination"))
    attention = any(sub.status in ATTENTION_STATUS for sub in subscriptions) or any(
        invoice.status == "failed" for invoice in invoices
    )
    return {
        "account": user,
        "subscriptions": subscriptions,
        "invoices": invoices,
        "companies": companies,
        "attention": attention,
        "has_password": user.has_usable_password(),
    }


def refresh_from_stripe(subscription) -> str:
    """Met à jour le statut local et les factures. Retourne ok, missing ou le message d'erreur."""
    if not subscription.stripe_subscription_id:
        return "missing"
    remote = retrieve_subscription(subscription.stripe_subscription_id)
    apply_subscription_object(remote)
    for invoice in list_invoices(subscription_id=subscription.stripe_subscription_id):
        failed = invoice.get("status") == "uncollectible" or (
            invoice.get("status") == "open"
            and not invoice.get("paid")
            and (invoice.get("attempt_count") or 0) > 0
        )
        record_invoice_receipt(invoice, failed=failed, touch_follow_up=False)
    return "ok"


class SubscriberListView(AdminStaffMixin, ListView):
    model = Subscription
    template_name = "admin_backoffice/billing_subscribers.html"
    context_object_name = "subscriptions"
    paginate_by = 20
    admin_section = "billing"
    crumbs_label = "Facturation"

    def get_queryset(self):
        qs = (
            Subscription.objects.select_related("user", "plan")
            .prefetch_related("user__companies")
            .order_by("-created_at")
        )
        self.q = (self.request.GET.get("q") or "").strip()
        self.status = (self.request.GET.get("status") or "").strip()
        self.plan = (self.request.GET.get("plan") or "").strip()
        self.follow = (self.request.GET.get("follow") or "").strip()
        if self.q:
            qs = qs.filter(
                Q(user__email__icontains=self.q)
                | Q(plan__name__icontains=self.q)
                | Q(plan__code__icontains=self.q)
                | Q(user__companies__denomination__icontains=self.q)
                | Q(user__companies__siren__icontains=self.q)
                | Q(stripe_subscription_id__icontains=self.q)
            ).distinct()
        if self.status in dict(Subscription.STATUSES):
            qs = qs.filter(status=self.status)
        if self.plan.isdigit():
            qs = qs.filter(plan_id=int(self.plan))
        if self.follow == "none":
            qs = qs.filter(follow_up="")
        elif self.follow in ("to_follow", "reminded", "resolved"):
            qs = qs.filter(follow_up=self.follow)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "q": self.q,
            "status": self.status,
            "plan": self.plan,
            "follow": self.follow,
            "statuses": Subscription.STATUSES,
            "plans": Plan.objects.order_by("price_eur", "name"),
            "follows": [("none", "Sans suivi")] + [
                item for item in Subscription.FOLLOW_UP if item[0]
            ],
        })
        return context


class SubscriberDetailView(AdminStaffMixin, DetailView):
    model = Subscription
    template_name = "admin_backoffice/billing_subscriber.html"
    context_object_name = "subscription"
    admin_section = "billing"
    crumbs_label = "Facturation"

    def get_queryset(self):
        return Subscription.objects.select_related("user", "plan").prefetch_related("user__companies")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        sub = self.object
        invoices = list(sub.invoices.all())
        context.update({
            "invoices": invoices,
            "companies": list(sub.user.companies.all()),
            "note_form": kwargs.get("note_form") or BillingNoteForm(initial={
                "follow_up": sub.follow_up,
                "staff_note": sub.staff_note,
            }),
            "attention": sub.status in ATTENTION_STATUS or any(inv.status == "failed" for inv in invoices),
            "has_password": sub.user.has_usable_password(),
        })
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        action = (request.POST.get("action") or "").strip()
        if action == "refresh":
            return self._refresh()
        if action == "note":
            return self._note()
        messages.error(request, "Action inconnue.")
        return redirect("admin_backoffice:billing_subscriber", pk=self.object.pk)

    def _refresh(self):
        sub = self.object
        try:
            result = refresh_from_stripe(sub)
        except StripeNotConfigured:
            messages.error(self.request, "Stripe n'est pas configuré. Le statut local est inchangé.")
            return redirect("admin_backoffice:billing_subscriber", pk=sub.pk)
        except StripeError as exc:
            messages.error(self.request, _safe_stripe_message(exc))
            return redirect("admin_backoffice:billing_subscriber", pk=sub.pk)
        if result == "missing":
            messages.info(
                self.request,
                "Cet abonnement n'est pas lié à Stripe. Le statut affiché est celui enregistré ici.",
            )
        else:
            messages.success(self.request, "Statut et factures rafraîchis depuis Stripe.")
            journaliser(self.request, f"Statut Stripe rafraîchi — {sub.user.email}")
        return redirect("admin_backoffice:billing_subscriber", pk=sub.pk)

    def _note(self):
        form = BillingNoteForm(self.request.POST)
        if not form.is_valid():
            messages.error(self.request, "La note n'a pas pu être enregistrée.")
            return self.render_to_response(self.get_context_data(note_form=form))
        sub = self.object
        sub.follow_up = form.cleaned_data.get("follow_up") or ""
        sub.staff_note = (form.cleaned_data.get("staff_note") or "")[:4000]
        sub.save(update_fields=["follow_up", "staff_note"])
        messages.success(self.request, "Note de facturation enregistrée.")
        journaliser(self.request, f"Note de facturation mise à jour — {sub.user.email}")
        return redirect("admin_backoffice:billing_subscriber", pk=sub.pk)


class BillingInvoiceListView(AdminStaffMixin, ListView):
    model = SubscriptionInvoice
    template_name = "admin_backoffice/billing_invoices.html"
    context_object_name = "invoices"
    paginate_by = 20
    admin_section = "billing"
    crumbs_label = "Facturation"

    def get_queryset(self):
        qs = (
            SubscriptionInvoice.objects.select_related("user", "subscription", "subscription__plan")
            .prefetch_related("user__companies")
            .order_by("-issued_at", "-created_at")
        )
        self.q = (self.request.GET.get("q") or "").strip()
        self.status = (self.request.GET.get("status") or "").strip()
        if self.q:
            qs = qs.filter(
                Q(user__email__icontains=self.q)
                | Q(number__icontains=self.q)
                | Q(description__icontains=self.q)
                | Q(user__companies__denomination__icontains=self.q)
                | Q(external_id__icontains=self.q)
            ).distinct()
        if self.status in dict(SubscriptionInvoice.STATUSES):
            qs = qs.filter(status=self.status)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "q": self.q,
            "status": self.status,
            "statuses": SubscriptionInvoice.STATUSES,
        })
        return context


class BillingInvoiceDetailView(AdminStaffMixin, DetailView):
    model = SubscriptionInvoice
    template_name = "admin_backoffice/billing_invoice.html"
    context_object_name = "invoice"
    admin_section = "billing"
    crumbs_label = "Facturation"

    def get_queryset(self):
        return SubscriptionInvoice.objects.select_related(
            "user", "subscription", "subscription__plan",
        ).prefetch_related("user__companies")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        invoice = self.object
        context.update({
            "companies": list(invoice.user.companies.all()),
            "note_form": kwargs.get("note_form") or InvoiceNoteForm(initial={"staff_note": invoice.staff_note}),
            "attention": invoice.status in ("failed", "open", "uncollectible"),
        })
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = InvoiceNoteForm(request.POST)
        if not form.is_valid():
            messages.error(request, "La note n'a pas pu être enregistrée.")
            return self.render_to_response(self.get_context_data(note_form=form))
        self.object.staff_note = (form.cleaned_data.get("staff_note") or "")[:4000]
        self.object.save(update_fields=["staff_note"])
        messages.success(request, "Note enregistrée.")
        journaliser(request, f"Note de facture d'abonnement mise à jour — {self.object.user.email}")
        return redirect("admin_backoffice:billing_invoice", pk=self.object.pk)


class UserBillingView(AdminStaffMixin, TemplateView):
    template_name = "admin_backoffice/billing_dossier.html"
    admin_section = "billing"
    crumbs_label = "Facturation"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = get_object_or_404(User, pk=self.kwargs["pk"])
        context.update(_dossier(user))
        context["heading"] = user.email
        context["intro"] = "Abonnement, encaissements et factures de ce compte."
        return context


class CompanyBillingView(AdminStaffMixin, TemplateView):
    template_name = "admin_backoffice/billing_dossier.html"
    admin_section = "billing"
    crumbs_label = "Facturation"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = get_object_or_404(Company.objects.select_related("owner"), pk=self.kwargs["pk"])
        context.update(_dossier(company.owner))
        context["company"] = company
        context["heading"] = company.denomination
        context["intro"] = (
            "La facturation de l'abonnement est rattachée au compte propriétaire. "
            "Les autres sociétés de ce compte partagent le même dossier."
        )
        return context
