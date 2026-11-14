from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.context import resolve_company
from documents.models import TicketDeCaisse
from mailsync.models import Supplier, SupplierInvoiceDraft

from .forms import PurchaseInvoiceForm, SupplierPaymentForm
from .models import STATUSES, PurchaseInvoice, SupplierPayment
from .services import (
    PurchaseError,
    delete_supplier_payment,
    post_purchase,
    register_supplier_payment,
)


def _company_or_redirect(request):
    company = resolve_company(request)
    if company is None:
        return None, redirect("onboarding")
    return company, None


def _scoped(company, pk):
    return get_object_or_404(
        PurchaseInvoice.objects.select_related("supplier", "journal_entry"),
        pk=pk,
        company=company,
    )


@login_required
def purchase_dashboard(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoices = PurchaseInvoice.objects.filter(company=company)
    approved = list(invoices.filter(status="approved").prefetch_related("payments"))
    unpaid = sum((invoice.amount_remaining for invoice in approved), Decimal("0.00"))
    overdue = [invoice for invoice in approved if invoice.is_late]
    today = timezone.localdate()
    month = invoices.filter(
        invoice_date__gte=today.replace(day=1), invoice_date__lte=today
    ).aggregate(
        ht=Sum("amount_ht"), vat=Sum("amount_vat"), ttc=Sum("amount_ttc")
    )
    recent = invoices.select_related("supplier")[:10]
    top_suppliers = (
        invoices.values("supplier_name")
        .annotate(total=Sum("amount_ttc"))
        .order_by("-total")[:5]
    )
    return render(
        request,
        "purchases/dashboard.html",
        {
            "company": company,
            "month_ht": month["ht"] or Decimal("0.00"),
            "month_vat": month["vat"] or Decimal("0.00"),
            "month_ttc": month["ttc"] or Decimal("0.00"),
            "unpaid": unpaid,
            "overdue": overdue,
            "recent": recent,
            "top_suppliers": top_suppliers,
            "supplier_count": Supplier.objects.filter(
                company=company, is_active=True
            ).count(),
            "mailsync_pending": SupplierInvoiceDraft.objects.filter(
                company=company, status="pending"
            ).count(),
            "tickets_pending": TicketDeCaisse.objects.filter(
                company=company, statut="brouillon"
            ).count(),
        },
    )


@login_required
def invoice_list(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    queryset = PurchaseInvoice.objects.filter(company=company).select_related(
        "supplier", "journal_entry"
    )
    status = (request.GET.get("statut") or "").strip()
    supplier_id = (request.GET.get("fournisseur") or "").strip()
    query = (request.GET.get("q") or "").strip()
    if status:
        queryset = queryset.filter(status=status)
    if supplier_id:
        queryset = queryset.filter(supplier_id=supplier_id)
    if query:
        from django.db.models import Q

        queryset = queryset.filter(
            Q(supplier_name__icontains=query) | Q(number__icontains=query)
        )
    return render(
        request,
        "purchases/list.html",
        {
            "company": company,
            "invoices": queryset,
            "status": status,
            "supplier_id": supplier_id,
            "query": query,
            "suppliers": Supplier.objects.filter(company=company).order_by("name"),
            "statuses": STATUSES,
        },
    )


@login_required
def invoice_create(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    form = PurchaseInvoiceForm(
        request.POST or None,
        request.FILES or None,
        company=company,
        initial={"supplier": request.GET.get("fournisseur") or None},
    )
    if request.method == "POST" and form.is_valid():
        invoice = form.save(commit=False)
        invoice.company = company
        invoice.status = "draft"
        invoice.source = "manual"
        invoice.save()
        messages.success(request, "Facture fournisseur enregistrée en brouillon.")
        return redirect("purchases:detail", pk=invoice.pk)
    return render(
        request,
        "purchases/form.html",
        {"company": company, "form": form, "invoice": None},
    )


@login_required
def invoice_detail(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoice = _scoped(company, pk)
    return render(
        request,
        "purchases/detail.html",
        {
            "company": company,
            "invoice": invoice,
            "payments": invoice.payments.select_related("journal_entry"),
        },
    )


@require_POST
@login_required
def invoice_approve(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoice = _scoped(company, pk)
    try:
        post_purchase(invoice)
    except PurchaseError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            "Facture validée : écriture ACH créée. Elle est désormais à payer.",
        )
    return redirect("purchases:detail", pk=invoice.pk)


@login_required
def invoice_pay(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoice = _scoped(company, pk)
    if invoice.status == "draft":
        messages.info(request, "Validez la facture avant d'enregistrer un règlement.")
        return redirect("purchases:detail", pk=invoice.pk)
    form = SupplierPaymentForm(request.POST or None, invoice=invoice)
    if request.method == "POST" and form.is_valid():
        try:
            register_supplier_payment(
                invoice,
                amount=form.cleaned_data["amount"],
                method=form.cleaned_data["method"],
                paid_at=form.cleaned_data["paid_at"],
                reference=form.cleaned_data.get("reference") or "",
                notes=form.cleaned_data.get("notes") or "",
            )
        except PurchaseError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Règlement enregistré au journal de banque.")
            return redirect("purchases:detail", pk=invoice.pk)
    return render(
        request,
        "purchases/payment_form.html",
        {"company": company, "invoice": invoice, "form": form},
    )


@require_POST
@login_required
def invoice_ignore(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoice = _scoped(company, pk)
    if invoice.payments.exists():
        messages.error(request, "Impossible d'ignorer une facture déjà réglée.")
    elif invoice.journal_entry_id:
        messages.error(
            request,
            "Impossible d'ignorer une facture déjà validée. Supprimez d'abord l'écriture.",
        )
    else:
        invoice.status = "ignored"
        invoice.save(update_fields=["status", "updated_at"])
        messages.info(request, "Facture ignorée.")
    return redirect("purchases:detail", pk=invoice.pk)


@login_required
def invoice_attachment(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoice = _scoped(company, pk)
    if not invoice.attachment:
        raise Http404("Aucun justificatif.")
    try:
        handle = invoice.attachment.open("rb")
    except FileNotFoundError as exc:
        raise Http404("Justificatif introuvable sur le stockage.") from exc
    return FileResponse(handle, as_attachment=True, filename=invoice.attachment_name or "facture")


@login_required
def payment_list(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    payments = SupplierPayment.objects.filter(company=company).select_related(
        "invoice", "invoice__supplier"
    )
    return render(
        request,
        "purchases/payments.html",
        {"company": company, "payments": payments},
    )


@require_POST
@login_required
def payment_delete(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    payment = get_object_or_404(SupplierPayment, pk=pk, company=company)
    invoice_id = payment.invoice_id
    delete_supplier_payment(payment)
    messages.success(request, "Règlement supprimé et écriture annulée.")
    return redirect("purchases:detail", pk=invoice_id)
