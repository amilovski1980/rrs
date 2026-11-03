import uuid
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.context import resolve_company

from .forms import InvoiceForm
from .models import Invoice
from .services import issue_invoice, pay_invoice, sync_sale


def _company_or_redirect(request):
    company = resolve_company(request)
    if company is None:
        return None, redirect("onboarding")
    return company, None


def _invoice(request, company, pk):
    return get_object_or_404(Invoice, pk=pk, company=company)


@login_required
def invoice_list(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoices = company.invoices.all()
    open_amount = sum(
        (inv.amount_ttc for inv in invoices if inv.status in ("issued", "late", "received")),
        Decimal("0.00"),
    )
    return render(request, "documents/invoice_list.html", {
        "company": company,
        "invoices": invoices,
        "open_amount": open_amount,
    })


@login_required
def invoice_create(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    form = InvoiceForm(request.POST or None, company=company)
    if request.method == "POST" and form.is_valid():
        invoice = form.save(commit=False)
        invoice.company = company
        invoice.status = "draft"
        invoice.number = f"BR-{uuid.uuid4().hex[:10]}"
        invoice.save()
        messages.success(request, "Brouillon enregistré. Émettez la facture pour la numéroter.")
        return redirect(reverse("invoice_detail", args=[invoice.id]) + f"?societe={company.id}")
    return render(request, "documents/invoice_form.html", {"company": company, "form": form})


@login_required
def invoice_edit(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoice = _invoice(request, company, pk)
    form = InvoiceForm(request.POST or None, instance=invoice, company=company)
    if request.method == "POST" and form.is_valid():
        form.save()
        if invoice.status != "draft":
            sync_sale(invoice)
            messages.success(request, "Facture mise à jour. Les écritures liées ont été recalculées.")
        else:
            messages.success(request, "Brouillon mis à jour.")
        return redirect(reverse("invoice_detail", args=[invoice.id]) + f"?societe={company.id}")
    return render(request, "documents/invoice_form.html", {
        "company": company,
        "form": form,
        "invoice": invoice,
    })


@login_required
def invoice_detail(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoice = _invoice(request, company, pk)
    return render(request, "documents/invoice_detail.html", {"company": company, "invoice": invoice})


@login_required
@require_POST
def invoice_issue(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoice = _invoice(request, company, pk)
    issue_invoice(invoice)
    messages.success(request, f"Facture {invoice.number} émise et passée au journal des ventes.")
    return redirect(reverse("invoice_detail", args=[invoice.id]) + f"?societe={company.id}")


@login_required
@require_POST
def invoice_pay(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoice = _invoice(request, company, pk)
    pay_invoice(invoice)
    messages.success(request, f"Encaissement de {invoice.number} enregistré en banque.")
    return redirect(reverse("invoice_detail", args=[invoice.id]) + f"?societe={company.id}")
