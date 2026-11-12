import logging

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q, Sum
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, ListView, TemplateView, UpdateView

from accounts.models import User
from ai.models import AiDraftEntry, Conversation, Message
from billing.models import Plan, Subscription
from companies.models import Company

from .access import staff_required, user_is_admin
from .agent_prompts import (
    DEFAULT_GLOBAL_PROMPT,
    TIER_LABELS,
    default_prompt_for_plan,
    effective_plan_prompt,
    global_prompt_text,
    tier_for_plan,
)
from .audit import journaliser
from .forms import (
    CompanyAdminForm,
    PlanAdminForm,
    SiteConfigurationForm,
    SmsSendForm,
    SmsTemplateForm,
    SubscriptionAdminForm,
    UserAdminForm,
)
from .integrations import integration_cards, probe
from .models import SiteConfiguration, SmsMessage, SmsTemplate, SystemLog
from .sms import (
    dispatch_sms,
    ensure_providers,
    get_settings,
    provider_card,
    save_provider_post,
    test_provider,
)

logger = logging.getLogger(__name__)


def _variation_pourcent(actuelle, precedente):
    """Variation entre deux périodes, en %. None s'il n'y a pas de base de comparaison."""
    if precedente <= 0:
        return None
    return round((actuelle - precedente) / precedente * 100)


def _serie_quotidienne(queryset, champ_date, jours, maintenant=None):
    """Compte journalier d'un queryset sur les N derniers jours (barres CSS sans librairie)."""
    maintenant = maintenant or timezone.now()
    serie = []
    for decalage in range(jours - 1, -1, -1):
        debut = (maintenant - timezone.timedelta(days=decalage)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        fin = debut + timezone.timedelta(days=1)
        total = queryset.filter(
            **{f"{champ_date}__gte": debut, f"{champ_date}__lt": fin}
        ).count()
        serie.append({"label": debut.strftime("%d/%m"), "total": total})
    maximum = max((point["total"] for point in serie), default=0)
    for point in serie:
        point["hauteur"] = round(point["total"] / maximum * 100) if maximum else 0
    return serie


class AdminStaffMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Réservé au personnel actif. Un client connecté reçoit 403, jamais le cockpit."""

    admin_section = ""
    crumbs_label = "Administration"

    def test_func(self):
        return user_is_admin(self.request.user)

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            raise PermissionDenied("Accès réservé à l'administration.")
        return super().handle_no_permission()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["admin_section"] = self.admin_section
        context["crumbs_label"] = self.crumbs_label
        return context


class AdminFormMixin(AdminStaffMixin):
    page_title = ""
    page_sub = ""
    cancel_url_name = ""
    success_message = "Enregistré."

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.page_title
        context["page_sub"] = self.page_sub
        if self.cancel_url_name:
            context["cancel_url"] = reverse(self.cancel_url_name)
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, self.success_message)
        journaliser(self.request, f"{self.success_message} — {self.object}")
        return response


class DashboardView(AdminStaffMixin, TemplateView):
    """Tableau de bord : indicateurs réels, tendances 30 j et graphique 14 j.

    Chaque famille d'indicateurs est isolée : un échec est journalisé et le
    reste du tableau de bord s'affiche quand même (état « indisponible »
    explicite, jamais un masquage silencieux).
    """

    template_name = "admin_backoffice/dashboard.html"
    admin_section = "dashboard"
    crumbs_label = "Vue d'ensemble"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        maintenant = timezone.now()
        limite_30j = maintenant - timezone.timedelta(days=30)
        limite_60j = maintenant - timezone.timedelta(days=60)

        context.update({
            "total_users": "—",
            "users_nouveaux_30j": None,
            "users_variation": None,
            "users_series": [],
            "recent_users": [],
            "total_companies": "—",
            "companies_nouveaux_30j": None,
            "companies_variation": None,
            "mrr": "—",
            "mrr_abonnements": None,
            "subs_past_due": 0,
            "subs_par_statut": [],
            "total_plans": "—",
            "plans_actifs": None,
            "ai_validation_rate": "—",
            "total_ai_drafts": "—",
            "ai_pending_drafts": "—",
            "ai_messages": None,
            "ai_conversations": None,
            "recent_companies": [],
            "recent_logs": [],
        })

        try:
            nouveaux_30j = User.objects.filter(created_at__gte=limite_30j).count()
            nouveaux_precedents = User.objects.filter(
                created_at__gte=limite_60j, created_at__lt=limite_30j
            ).count()
            context.update({
                "total_users": User.objects.count(),
                "users_nouveaux_30j": nouveaux_30j,
                "users_variation": _variation_pourcent(nouveaux_30j, nouveaux_precedents),
                "users_series": _serie_quotidienne(User.objects, "created_at", 14, maintenant),
                "recent_users": User.objects.order_by("-created_at")[:6],
            })
        except Exception as exc:
            logger.error("Dashboard : indicateurs utilisateurs indisponibles : %s", exc)
            context["users_indisponible"] = True

        try:
            societes_30j = Company.objects.filter(created_at__gte=limite_30j).count()
            societes_precedentes = Company.objects.filter(
                created_at__gte=limite_60j, created_at__lt=limite_30j
            ).count()
            context.update({
                "total_companies": Company.objects.count(),
                "recent_companies": Company.objects.select_related("owner").order_by("-created_at")[:5],
                "companies_nouveaux_30j": societes_30j,
                "companies_variation": _variation_pourcent(societes_30j, societes_precedentes),
            })
        except Exception as exc:
            logger.error("Dashboard : indicateurs sociétés indisponibles : %s", exc)
            context["companies_indisponible"] = True

        try:
            abonnements_actifs = Subscription.objects.filter(status__in=["active", "trialing"])
            mrr_val = abonnements_actifs.aggregate(total=Sum("plan__price_eur"))["total"] or 0
            par_statut = {
                ligne["status"]: ligne["total"]
                for ligne in Subscription.objects.values("status").annotate(total=Count("id"))
            }
            context.update({
                "mrr": f"{mrr_val:,.2f} €",
                "mrr_abonnements": abonnements_actifs.count(),
                "subs_past_due": par_statut.get("past_due", 0),
                "subs_par_statut": [
                    {"code": code, "label": label, "total": par_statut.get(code, 0)}
                    for code, label in Subscription.STATUSES
                ],
                "total_plans": Plan.objects.count(),
                "plans_actifs": Plan.objects.filter(is_active=True).count(),
            })
        except Exception as exc:
            logger.error("Dashboard : indicateurs facturation indisponibles : %s", exc)
            context["facturation_indisponible"] = True

        try:
            drafts = AiDraftEntry.objects.all()
            total = drafts.count()
            valides = drafts.filter(status="validated").count()
            context.update({
                "ai_validation_rate": f"{(valides / total * 100):.1f}%" if total > 0 else "0%",
                "total_ai_drafts": total,
                "ai_pending_drafts": drafts.filter(status="pending").count(),
                "ai_messages": Message.objects.count(),
                "ai_conversations": Conversation.objects.count(),
            })
        except Exception as exc:
            logger.error("Dashboard : indicateurs IA indisponibles : %s", exc)
            context["ia_indisponible"] = True

        try:
            context["recent_logs"] = SystemLog.objects.select_related("user").order_by("-timestamp")[:8]
        except Exception as exc:
            logger.error("Dashboard : journal système indisponible : %s", exc)
            context["logs_indisponible"] = True

        return context


class SiteSettingsView(AdminStaffMixin, TemplateView):
    template_name = "admin_backoffice/settings.html"
    admin_section = "settings"
    crumbs_label = "Paramètres"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        config, _ = SiteConfiguration.objects.get_or_create(id=1)
        context["config"] = config
        context["form"] = kwargs.get("form") or SiteConfigurationForm(instance=config)
        context["secrets"] = {
            "smtp_password": bool(config.smtp_password),
            "stripe_secret_key": bool(config.stripe_secret_key),
            "llm_api_key": bool(config.llm_api_key),
            "insee_api_key": bool(config.insee_api_key),
        }
        return context

    def post(self, request, *args, **kwargs):
        config, _ = SiteConfiguration.objects.get_or_create(id=1)
        form = SiteConfigurationForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, "Configuration mise à jour.")
            journaliser(request, "Configuration du site mise à jour.")
            return redirect("admin_backoffice:settings")
        messages.error(request, "La configuration n'a pas pu être enregistrée.")
        return self.render_to_response(self.get_context_data(form=form))


class CompanyListView(AdminStaffMixin, ListView):
    model = Company
    template_name = "admin_backoffice/companies_list.html"
    context_object_name = "companies"
    paginate_by = 20
    admin_section = "companies"
    crumbs_label = "Sociétés"

    def get_queryset(self):
        qs = Company.objects.select_related("owner").order_by("-created_at")
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(denomination__icontains=q) | Q(siren__icontains=q) | Q(owner__email__icontains=q)
            )
        self.q = q
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = getattr(self, "q", "")
        return context


class CompanyCreateView(AdminFormMixin, CreateView):
    model = Company
    form_class = CompanyAdminForm
    template_name = "admin_backoffice/form_page.html"
    success_url = reverse_lazy("admin_backoffice:companies")
    admin_section = "companies"
    crumbs_label = "Sociétés"
    page_title = "Nouvelle société"
    page_sub = "Création manuelle, hors parcours d'inscription client."
    cancel_url_name = "admin_backoffice:companies"
    success_message = "Société créée."


class CompanyUpdateView(AdminFormMixin, UpdateView):
    model = Company
    form_class = CompanyAdminForm
    template_name = "admin_backoffice/form_page.html"
    success_url = reverse_lazy("admin_backoffice:companies")
    admin_section = "companies"
    crumbs_label = "Sociétés"
    page_title = "Modifier la société"
    page_sub = "Identité, régime et propriétaire."
    cancel_url_name = "admin_backoffice:companies"
    success_message = "Société mise à jour."


class CompanyDeleteView(AdminStaffMixin, DeleteView):
    model = Company
    template_name = "admin_backoffice/confirm_delete.html"
    success_url = reverse_lazy("admin_backoffice:companies")
    admin_section = "companies"
    crumbs_label = "Sociétés"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cancel_url"] = self.success_url
        return context

    def form_valid(self, form):
        messages.success(self.request, "Société supprimée.")
        journaliser(self.request, f"Société supprimée — {self.object}")
        return super().form_valid(form)


class PlanListView(AdminStaffMixin, ListView):
    model = Plan
    template_name = "admin_backoffice/plans_list.html"
    context_object_name = "plans"
    admin_section = "plans"
    crumbs_label = "Forfaits"

    def get_queryset(self):
        return Plan.objects.annotate(abonnes=Count("subscription")).order_by("price_eur", "name")


class PlanCreateView(AdminFormMixin, CreateView):
    model = Plan
    form_class = PlanAdminForm
    template_name = "admin_backoffice/form_page.html"
    success_url = reverse_lazy("admin_backoffice:plans")
    admin_section = "plans"
    crumbs_label = "Forfaits"
    page_title = "Nouveau forfait"
    page_sub = "Prix, limites, fonctions et consigne de l'agent."
    cancel_url_name = "admin_backoffice:plans"
    success_message = "Forfait créé."


class PlanUpdateView(AdminFormMixin, UpdateView):
    model = Plan
    form_class = PlanAdminForm
    template_name = "admin_backoffice/form_page.html"
    success_url = reverse_lazy("admin_backoffice:plans")
    admin_section = "plans"
    crumbs_label = "Forfaits"
    page_title = "Modifier le forfait"
    page_sub = "Prix, limites, fonctions et consigne de l'agent."
    cancel_url_name = "admin_backoffice:plans"
    success_message = "Forfait mis à jour."


class PlanDeleteView(AdminStaffMixin, DeleteView):
    model = Plan
    template_name = "admin_backoffice/confirm_delete.html"
    success_url = reverse_lazy("admin_backoffice:plans")
    admin_section = "plans"
    crumbs_label = "Forfaits"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cancel_url"] = self.success_url
        return context

    def form_valid(self, form):
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(self.request, "Ce forfait est encore utilisé par des abonnements.")
            return redirect("admin_backoffice:plans")
        messages.success(self.request, "Forfait supprimé.")
        journaliser(self.request, "Forfait supprimé.")
        return response


class SubscriptionListView(AdminStaffMixin, ListView):
    model = Subscription
    template_name = "admin_backoffice/subscriptions_list.html"
    context_object_name = "subscriptions"
    paginate_by = 20
    admin_section = "subscriptions"
    crumbs_label = "Abonnements"

    def get_queryset(self):
        qs = Subscription.objects.select_related("user", "plan").order_by("-created_at")
        self.q = (self.request.GET.get("q") or "").strip()
        self.status = (self.request.GET.get("status") or "").strip()
        if self.q:
            qs = qs.filter(Q(user__email__icontains=self.q) | Q(plan__name__icontains=self.q))
        if self.status:
            qs = qs.filter(status=self.status)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = self.q
        context["status"] = self.status
        context["statuses"] = Subscription.STATUSES
        return context


class SubscriptionCreateView(AdminFormMixin, CreateView):
    model = Subscription
    form_class = SubscriptionAdminForm
    template_name = "admin_backoffice/form_page.html"
    success_url = reverse_lazy("admin_backoffice:subscriptions")
    admin_section = "subscriptions"
    crumbs_label = "Abonnements"
    page_title = "Nouvel abonnement"
    page_sub = "Rattache un utilisateur à un forfait."
    cancel_url_name = "admin_backoffice:subscriptions"
    success_message = "Abonnement créé."


class SubscriptionUpdateView(AdminFormMixin, UpdateView):
    model = Subscription
    form_class = SubscriptionAdminForm
    template_name = "admin_backoffice/form_page.html"
    success_url = reverse_lazy("admin_backoffice:subscriptions")
    admin_section = "subscriptions"
    crumbs_label = "Abonnements"
    page_title = "Modifier l'abonnement"
    page_sub = "Statut, forfait et fin de période."
    cancel_url_name = "admin_backoffice:subscriptions"
    success_message = "Abonnement mis à jour."


class SubscriptionDeleteView(AdminStaffMixin, DeleteView):
    model = Subscription
    template_name = "admin_backoffice/confirm_delete.html"
    success_url = reverse_lazy("admin_backoffice:subscriptions")
    admin_section = "subscriptions"
    crumbs_label = "Abonnements"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cancel_url"] = self.success_url
        return context

    def form_valid(self, form):
        messages.success(self.request, "Abonnement supprimé.")
        journaliser(self.request, f"Abonnement supprimé — {self.object}")
        return super().form_valid(form)


class UserListView(AdminStaffMixin, ListView):
    model = User
    template_name = "admin_backoffice/users_list.html"
    context_object_name = "users"
    paginate_by = 20
    admin_section = "users"
    crumbs_label = "Utilisateurs"

    def get_queryset(self):
        qs = User.objects.all().order_by("-created_at")
        self.q = (self.request.GET.get("q") or "").strip()
        self.role = (self.request.GET.get("role") or "").strip()
        self.active = (self.request.GET.get("active") or "").strip()
        self.phone = (self.request.GET.get("phone") or "").strip()
        if self.q:
            qs = qs.filter(Q(email__icontains=self.q) | Q(phone__icontains=self.q))
        if self.role == "superuser":
            qs = qs.filter(is_superuser=True)
        elif self.role == "staff":
            qs = qs.filter(is_staff=True, is_superuser=False)
        elif self.role == "client":
            qs = qs.filter(is_staff=False, is_superuser=False)
        if self.active in ("0", "1"):
            qs = qs.filter(is_active=self.active == "1")
        if self.phone in ("0", "1"):
            qs = qs.filter(phone_verified=self.phone == "1")
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "q": self.q,
            "role": self.role,
            "active": self.active,
            "phone": self.phone,
        })
        return context


class UserCreateView(AdminFormMixin, CreateView):
    model = User
    form_class = UserAdminForm
    template_name = "admin_backoffice/form_page.html"
    success_url = reverse_lazy("admin_backoffice:users")
    admin_section = "users"
    crumbs_label = "Utilisateurs"
    page_title = "Nouvel utilisateur"
    page_sub = "Connexion par lien magique : aucun mot de passe n'est défini."
    cancel_url_name = "admin_backoffice:users"
    success_message = "Utilisateur créé."

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["actor"] = self.request.user
        return kwargs


class UserUpdateView(AdminFormMixin, UpdateView):
    model = User
    form_class = UserAdminForm
    template_name = "admin_backoffice/form_page.html"
    success_url = reverse_lazy("admin_backoffice:users")
    admin_section = "users"
    crumbs_label = "Utilisateurs"
    page_title = "Modifier l'utilisateur"
    page_sub = "Rôle, activation et téléphone."
    cancel_url_name = "admin_backoffice:users"
    success_message = "Utilisateur mis à jour."

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if obj.is_superuser and not self.request.user.is_superuser:
            raise PermissionDenied("Seul un super-administrateur peut modifier ce compte.")
        return obj

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["actor"] = self.request.user
        return kwargs


class UserDeleteView(AdminStaffMixin, DeleteView):
    model = User
    template_name = "admin_backoffice/confirm_delete.html"
    success_url = reverse_lazy("admin_backoffice:users")
    admin_section = "users"
    crumbs_label = "Utilisateurs"

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if obj.is_superuser and not self.request.user.is_superuser:
            raise PermissionDenied("Seul un super-administrateur peut supprimer ce compte.")
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cancel_url"] = self.success_url
        return context

    def form_valid(self, form):
        if self.object.pk == self.request.user.pk:
            messages.error(self.request, "Vous ne pouvez pas supprimer votre propre compte.")
            return redirect("admin_backoffice:users")
        journaliser(self.request, f"Utilisateur supprimé — {self.object.email}")
        messages.success(self.request, "Utilisateur supprimé.")
        return super().form_valid(form)


@staff_required
@require_POST
def user_toggle(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user.pk == request.user.pk:
        messages.error(request, "Vous ne pouvez pas désactiver votre propre compte.")
        return redirect("admin_backoffice:users")
    if user.is_superuser and not request.user.is_superuser:
        raise PermissionDenied("Seul un super-administrateur peut modifier ce compte.")
    user.is_active = not user.is_active
    user.save(update_fields=["is_active"])
    etat = "activé" if user.is_active else "désactivé"
    messages.success(request, f"Compte {etat}.")
    journaliser(request, f"Compte {etat} — {user.email}")
    return redirect("admin_backoffice:users")


@staff_required
@require_POST
def impersonate_start(request, pk):
    """Ouvre le cockpit d'un client. Jamais un compte staff ou inactif."""
    target = get_object_or_404(User, pk=pk)
    if target.pk == request.user.pk or target.is_staff or target.is_superuser or not target.is_active:
        raise PermissionDenied("Ce compte ne peut pas être consulté ainsi.")
    if request.session.get("admin_impersonator_id"):
        raise PermissionDenied("Une consultation est déjà en cours.")
    admin_id = str(request.user.pk)
    admin_email = request.user.email
    journaliser(request, f"Consultation du cockpit de {target.email}")
    auth_login(request, target, backend="django.contrib.auth.backends.ModelBackend")
    request.session["admin_impersonator_id"] = admin_id
    request.session["admin_impersonator_email"] = admin_email
    return redirect("cockpit")


@require_POST
def impersonate_stop(request):
    admin_id = request.session.get("admin_impersonator_id")
    if not admin_id:
        raise PermissionDenied("Aucune consultation en cours.")
    admin = User.objects.filter(pk=admin_id, is_active=True, is_staff=True).first()
    if admin is None:
        request.session.pop("admin_impersonator_id", None)
        raise PermissionDenied("Le compte administrateur d'origine n'est plus valide.")
    consulted = request.user.email if request.user.is_authenticated else ""
    auth_login(request, admin, backend="django.contrib.auth.backends.ModelBackend")
    journaliser(request, f"Fin de consultation du cockpit de {consulted}", user=admin)
    messages.success(request, "Vous êtes de retour dans l'administration.")
    return redirect("admin_backoffice:users")


class SystemLogsView(AdminStaffMixin, ListView):
    model = SystemLog
    template_name = "admin_backoffice/logs.html"
    context_object_name = "logs"
    paginate_by = 50
    admin_section = "logs"
    crumbs_label = "Journal"

    def get_queryset(self):
        qs = SystemLog.objects.select_related("user").order_by("-timestamp")
        self.q = (self.request.GET.get("q") or "").strip()
        self.level = (self.request.GET.get("level") or "").strip()
        if self.q:
            qs = qs.filter(message__icontains=self.q)
        if self.level:
            qs = qs.filter(level=self.level)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = self.q
        context["level"] = self.level
        context["levels"] = SystemLog.LEVELS
        return context


class AiMonitoringView(AdminStaffMixin, TemplateView):
    template_name = "admin_backoffice/ai_monitoring.html"
    admin_section = "ai"
    crumbs_label = "Suivi IA"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        drafts = AiDraftEntry.objects.select_related("company")
        context["total_drafts"] = drafts.count()
        context["validated_count"] = drafts.filter(status="validated").count()
        context["rejected_count"] = drafts.filter(status="rejected").count()
        context["pending_count"] = drafts.filter(status="pending").count()
        context["recent_drafts"] = drafts.order_by("-created_at")[:12]
        context["conversations"] = Conversation.objects.count()
        context["messages_count"] = Message.objects.count()
        context["by_model"] = list(
            drafts.values("model_name").annotate(total=Count("id")).order_by("-total")[:6]
        )
        return context


class AiPromptView(AdminStaffMixin, TemplateView):
    template_name = "admin_backoffice/ai_prompt.html"
    admin_section = "prompts"
    crumbs_label = "Consignes de l'agent"

    def _plans(self):
        peers = list(Plan.objects.order_by("price_eur", "name"))
        rows = []
        for plan in peers:
            rows.append({
                "plan": plan,
                "prompt": effective_plan_prompt(plan),
                "tier_label": TIER_LABELS.get(tier_for_plan(plan, peers), ""),
                "field": f"plan_prompt_{plan.pk}",
                "custom": bool((plan.ai_prompt or "").strip()),
            })
        return rows

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["current_prompt"] = global_prompt_text()
        context["plans"] = self._plans()
        return context

    def post(self, request, *args, **kwargs):
        from django.conf import settings

        new_prompt = request.POST.get("prompt")
        if new_prompt is not None:
            config, _ = SiteConfiguration.objects.get_or_create(id=1)
            text = new_prompt.strip()
            config.ai_system_prompt = "" if text == DEFAULT_GLOBAL_PROMPT.strip() else text
            config.save(update_fields=["ai_system_prompt"])
            settings.AI_SYSTEM_PROMPT = text or DEFAULT_GLOBAL_PROMPT
        peers = list(Plan.objects.all())
        for plan in peers:
            key = f"plan_prompt_{plan.pk}"
            if key not in request.POST:
                continue
            submitted = request.POST.get(key, "").strip()
            default = default_prompt_for_plan(plan).strip()
            plan.ai_prompt = "" if submitted == default else submitted
            plan.save(update_fields=["ai_prompt"])
        messages.success(request, "Consignes de l'agent enregistrées.")
        journaliser(request, "Consignes de l'agent IA mises à jour.")
        return redirect("admin_backoffice:ai_prompt")


class IntegrationsView(AdminStaffMixin, TemplateView):
    template_name = "admin_backoffice/integrations.html"
    admin_section = "integrations"
    crumbs_label = "Intégrations"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cards"] = integration_cards()
        return context


@staff_required
@require_POST
def integrations_test(request, code):
    result = probe(code)
    journaliser(request, f"Test d'intégration {code} — {'ok' if result.get('ok') else 'échec'}")
    if result.get("ok"):
        messages.success(request, result["message"])
    else:
        messages.warning(request, result["message"])
    return redirect("admin_backoffice:integrations")


class SmsView(AdminStaffMixin, TemplateView):
    template_name = "admin_backoffice/sms.html"
    admin_section = "sms"
    crumbs_label = "SMS"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        settings_row = get_settings()
        context["active_provider"] = settings_row.active_provider
        context["providers"] = [provider_card(row) for row in ensure_providers()]
        context["templates"] = SmsTemplate.objects.all()
        context["messages_log"] = SmsMessage.objects.select_related("template", "created_by")[:40]
        context["send_form"] = kwargs.get("send_form") or SmsSendForm()
        context["template_form"] = kwargs.get("template_form") or SmsTemplateForm()
        return context

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action") or "config"
        if action == "template":
            form = SmsTemplateForm(request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, "Modèle SMS enregistré.")
                journaliser(request, f"Modèle SMS créé — {form.instance.code}")
                return redirect("admin_backoffice:sms")
            messages.error(request, "Le modèle SMS n'a pas pu être enregistré.")
            return self.render_to_response(self.get_context_data(template_form=form))
        if action == "send":
            form = SmsSendForm(request.POST)
            if form.is_valid():
                entry = dispatch_sms(
                    recipient=form.cleaned_data["recipient"],
                    body=form.cleaned_data["body"],
                    template=form.cleaned_data.get("template"),
                    actor=request.user,
                )
                messages.info(request, f"Journal SMS : {entry.get_status_display()}. {entry.detail}")
                journaliser(request, f"Tentative SMS vers {entry.recipient} — {entry.status}")
                return redirect("admin_backoffice:sms")
            messages.error(request, "L'envoi n'a pas pu être journalisé.")
            return self.render_to_response(self.get_context_data(send_form=form))
        notice = save_provider_post(request)
        messages.success(request, notice)
        journaliser(request, "Configuration SMS mise à jour.")
        return redirect("admin_backoffice:sms")


@staff_required
@require_POST
def sms_test(request, code):
    result = test_provider(code)
    journaliser(request, f"Test SMS {code} — {'ok' if result.get('ok') else 'incomplet'}")
    if result.get("ok"):
        messages.success(request, result["message"])
    else:
        messages.warning(request, result["message"])
    return redirect("admin_backoffice:sms")


class SmsTemplateUpdateView(AdminFormMixin, UpdateView):
    model = SmsTemplate
    form_class = SmsTemplateForm
    template_name = "admin_backoffice/form_page.html"
    success_url = reverse_lazy("admin_backoffice:sms")
    admin_section = "sms"
    crumbs_label = "SMS"
    page_title = "Modifier le modèle SMS"
    page_sub = "Le texte est journalisé tel quel tant qu'aucun fournisseur n'envoie réellement."
    cancel_url_name = "admin_backoffice:sms"
    success_message = "Modèle SMS mis à jour."


class SmsTemplateDeleteView(AdminStaffMixin, DeleteView):
    model = SmsTemplate
    template_name = "admin_backoffice/confirm_delete.html"
    success_url = reverse_lazy("admin_backoffice:sms")
    admin_section = "sms"
    crumbs_label = "SMS"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cancel_url"] = self.success_url
        return context

    def form_valid(self, form):
        messages.success(self.request, "Modèle SMS supprimé.")
        journaliser(self.request, f"Modèle SMS supprimé — {self.object}")
        return super().form_valid(form)


@staff_required
def health_check(request):
    return HttpResponse("Admin Backoffice is ALIVE")
