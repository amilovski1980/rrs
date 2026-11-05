import uuid
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from companies.models import INVOICE_THEMES
from core.context import resolve_company

from .forms import (
    ClientForm,
    CreditNoteForm,
    InvoiceForm,
    PaymentForm,
    PdfImportForm,
    ProductForm,
    ProjectForm,
    QuoteForm,
)
from .models import Client, CreditNote, Invoice, Payment, Product, Project, Quote
from .pdf import render_invoice_pdf
from .pdf_import import PdfImportError, import_invoice_pdf
from .services import (
    convert_quote_to_invoice,
    issue_credit_note,
    issue_invoice,
    issue_quote_number,
    pay_invoice,
    register_payment,
    sync_sale,
)


def _company_or_redirect(request):
    company = resolve_company(request)
    if company is None:
        return None, redirect("onboarding")
    return company, None


def _scoped(model, company, pk):
    return get_object_or_404(model, pk=pk, company=company)


def _qs(company):
    return f"?societe={company.id}"


# ---------------------------------------------------------------------------
# Factures (existant enrichi)
# ---------------------------------------------------------------------------


@login_required
def invoice_list(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoices = company.invoices.all()
    open_amount = sum(
        (inv.amount_remaining for inv in invoices if inv.status in ("issued", "late", "received")),
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
        return redirect(reverse("invoice_detail", args=[invoice.id]) + _qs(company))
    return render(request, "documents/invoice_form.html", {"company": company, "form": form})


@login_required
def invoice_edit(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoice = _scoped(Invoice, company, pk)
    form = InvoiceForm(request.POST or None, instance=invoice, company=company)
    if request.method == "POST" and form.is_valid():
        form.save()
        if invoice.status != "draft":
            sync_sale(invoice)
            messages.success(request, "Facture mise à jour. Les écritures liées ont été recalculées.")
        else:
            messages.success(request, "Brouillon mis à jour.")
        return redirect(reverse("invoice_detail", args=[invoice.id]) + _qs(company))
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
    invoice = _scoped(Invoice, company, pk)
    return render(request, "documents/invoice_detail.html", {
        "company": company,
        "invoice": invoice,
        "themes": INVOICE_THEMES,
        "payments": invoice.payments.all(),
        "credit_notes": invoice.credit_notes.all(),
        "lines": invoice.lines.all(),
    })


@login_required
def invoice_pdf(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoice = _scoped(Invoice, company, pk)
    payload = render_invoice_pdf(invoice, company)
    response = HttpResponse(payload, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{invoice.number}.pdf"'
    return response


@login_required
@require_POST
def invoice_issue(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoice = _scoped(Invoice, company, pk)
    issue_invoice(invoice)
    messages.success(request, f"Facture {invoice.number} émise et passée au journal des ventes.")
    return redirect(reverse("invoice_detail", args=[invoice.id]) + _qs(company))


@login_required
@require_POST
def invoice_pay(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoice = _scoped(Invoice, company, pk)
    pay_invoice(invoice)
    messages.success(request, f"Encaissement de {invoice.number} enregistré en banque.")
    return redirect(reverse("invoice_detail", args=[invoice.id]) + _qs(company))


@login_required
@require_POST
def invoice_delete(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoice = _scoped(Invoice, company, pk)
    if invoice.status != "draft":
        messages.error(request, "Seuls les brouillons peuvent être supprimés.")
        return redirect(reverse("invoice_detail", args=[invoice.id]) + _qs(company))
    invoice.delete()
    messages.success(request, "Brouillon supprimé.")
    return redirect(reverse("invoices") + _qs(company))


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------


@login_required
def client_list(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    return render(request, "documents/client_list.html", {
        "company": company,
        "clients": company.clients.all(),
    })


@login_required
def client_create(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    form = ClientForm(request.POST or None, company=company)
    if request.method == "POST" and form.is_valid():
        client = form.save(commit=False)
        client.company = company
        client.save()
        messages.success(request, "Client créé.")
        return redirect(reverse("client_detail", args=[client.id]) + _qs(company))
    return render(request, "documents/client_form.html", {"company": company, "form": form})


@login_required
def client_edit(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    client = _scoped(Client, company, pk)
    form = ClientForm(request.POST or None, instance=client, company=company)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Client mis à jour.")
        return redirect(reverse("client_detail", args=[client.id]) + _qs(company))
    return render(request, "documents/client_form.html", {
        "company": company, "form": form, "client": client,
    })


@login_required
def client_detail(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    client = _scoped(Client, company, pk)
    return render(request, "documents/client_detail.html", {
        "company": company,
        "client": client,
        "invoices": client.invoices.all()[:20],
        "quotes": client.quotes.all()[:20],
        "projects": client.projects.all()[:20],
    })


@login_required
@require_POST
def client_delete(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    client = _scoped(Client, company, pk)
    client.delete()
    messages.success(request, "Client supprimé.")
    return redirect(reverse("clients") + _qs(company))


# ---------------------------------------------------------------------------
# Produits / services
# ---------------------------------------------------------------------------


@login_required
def product_list(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    return render(request, "documents/product_list.html", {
        "company": company,
        "products": company.products.all(),
    })


@login_required
def product_create(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    form = ProductForm(request.POST or None, company=company)
    if request.method == "POST" and form.is_valid():
        product = form.save(commit=False)
        product.company = company
        product.save()
        messages.success(request, "Produit / service créé.")
        return redirect(reverse("product_detail", args=[product.id]) + _qs(company))
    return render(request, "documents/product_form.html", {"company": company, "form": form})


@login_required
def product_edit(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    product = _scoped(Product, company, pk)
    form = ProductForm(request.POST or None, instance=product, company=company)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Produit / service mis à jour.")
        return redirect(reverse("product_detail", args=[product.id]) + _qs(company))
    return render(request, "documents/product_form.html", {
        "company": company, "form": form, "product": product,
    })


@login_required
def product_detail(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    product = _scoped(Product, company, pk)
    return render(request, "documents/product_detail.html", {
        "company": company, "product": product,
    })


@login_required
@require_POST
def product_delete(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    product = _scoped(Product, company, pk)
    product.delete()
    messages.success(request, "Produit / service supprimé.")
    return redirect(reverse("products") + _qs(company))


# ---------------------------------------------------------------------------
# Projets
# ---------------------------------------------------------------------------


@login_required
def project_list(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    return render(request, "documents/project_list.html", {
        "company": company,
        "projects": company.projects.select_related("client").all(),
    })


@login_required
def project_create(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    form = ProjectForm(request.POST or None, company=company)
    if request.method == "POST" and form.is_valid():
        project = form.save(commit=False)
        project.company = company
        project.save()
        messages.success(request, "Projet créé.")
        return redirect(reverse("project_detail", args=[project.id]) + _qs(company))
    return render(request, "documents/project_form.html", {"company": company, "form": form})


@login_required
def project_edit(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    project = _scoped(Project, company, pk)
    form = ProjectForm(request.POST or None, instance=project, company=company)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Projet mis à jour.")
        return redirect(reverse("project_detail", args=[project.id]) + _qs(company))
    return render(request, "documents/project_form.html", {
        "company": company, "form": form, "project": project,
    })


@login_required
def project_detail(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    project = _scoped(Project, company, pk)
    return render(request, "documents/project_detail.html", {
        "company": company,
        "project": project,
        "invoices": project.invoices.all()[:20],
        "quotes": project.quotes.all()[:20],
    })


@login_required
@require_POST
def project_delete(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    project = _scoped(Project, company, pk)
    project.delete()
    messages.success(request, "Projet supprimé.")
    return redirect(reverse("projects") + _qs(company))


# ---------------------------------------------------------------------------
# Devis
# ---------------------------------------------------------------------------


@login_required
def quote_list(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    return render(request, "documents/quote_list.html", {
        "company": company,
        "quotes": company.quotes.all(),
    })


@login_required
def quote_create(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    form = QuoteForm(request.POST or None, company=company)
    if request.method == "POST" and form.is_valid():
        quote = form.save(commit=False)
        quote.company = company
        quote.status = "draft"
        quote.number = f"BR-{uuid.uuid4().hex[:10]}"
        quote.save()
        messages.success(request, "Devis enregistré en brouillon.")
        return redirect(reverse("quote_detail", args=[quote.id]) + _qs(company))
    return render(request, "documents/quote_form.html", {"company": company, "form": form})


@login_required
def quote_edit(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    quote = _scoped(Quote, company, pk)
    if quote.status == "converted":
        messages.error(request, "Un devis converti ne peut plus être modifié.")
        return redirect(reverse("quote_detail", args=[quote.id]) + _qs(company))
    form = QuoteForm(request.POST or None, instance=quote, company=company)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Devis mis à jour.")
        return redirect(reverse("quote_detail", args=[quote.id]) + _qs(company))
    return render(request, "documents/quote_form.html", {
        "company": company, "form": form, "quote": quote,
    })


@login_required
def quote_detail(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    quote = _scoped(Quote, company, pk)
    return render(request, "documents/quote_detail.html", {
        "company": company, "quote": quote, "lines": quote.lines.all(),
    })


@login_required
@require_POST
def quote_issue(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    quote = _scoped(Quote, company, pk)
    issue_quote_number(quote)
    messages.success(request, f"Devis {quote.number} numéroté.")
    return redirect(reverse("quote_detail", args=[quote.id]) + _qs(company))


@login_required
@require_POST
def quote_convert(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    quote = _scoped(Quote, company, pk)
    try:
        invoice = convert_quote_to_invoice(quote)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect(reverse("quote_detail", args=[quote.id]) + _qs(company))
    messages.success(
        request,
        f"Devis converti en facture brouillon {invoice.number}. "
        "Émettez-la pour consommer un numéro de facture.",
    )
    return redirect(reverse("invoice_detail", args=[invoice.id]) + _qs(company))


@login_required
@require_POST
def quote_delete(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    quote = _scoped(Quote, company, pk)
    if quote.status == "converted":
        messages.error(request, "Un devis converti ne peut pas être supprimé.")
        return redirect(reverse("quote_detail", args=[quote.id]) + _qs(company))
    quote.delete()
    messages.success(request, "Devis supprimé.")
    return redirect(reverse("quotes") + _qs(company))


# ---------------------------------------------------------------------------
# Avoirs
# ---------------------------------------------------------------------------


@login_required
def credit_note_list(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    return render(request, "documents/credit_note_list.html", {
        "company": company,
        "credit_notes": company.credit_notes.select_related("invoice").all(),
    })


@login_required
def credit_note_create(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    initial = {}
    invoice_id = request.GET.get("facture")
    if invoice_id:
        inv = company.invoices.filter(pk=invoice_id).first()
        if inv:
            initial = {
                "invoice": inv,
                "amount_ht": inv.amount_ht,
                "vat_rate": inv.vat_rate,
            }
    form = CreditNoteForm(request.POST or None, company=company, initial=initial)
    if request.method == "POST" and form.is_valid():
        note = form.save(commit=False)
        note.company = company
        note.status = "draft"
        note.number = f"BR-{uuid.uuid4().hex[:10]}"
        if note.invoice_id and note.invoice.company_id != company.id:
            messages.error(request, "Facture hors société.")
            return redirect(reverse("credit_notes") + _qs(company))
        note.save()
        messages.success(request, "Avoir enregistré en brouillon.")
        return redirect(reverse("credit_note_detail", args=[note.id]) + _qs(company))
    return render(request, "documents/credit_note_form.html", {"company": company, "form": form})


@login_required
def credit_note_detail(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    note = _scoped(CreditNote, company, pk)
    return render(request, "documents/credit_note_detail.html", {
        "company": company, "credit_note": note,
    })


@login_required
def credit_note_edit(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    note = _scoped(CreditNote, company, pk)
    if note.status != "draft":
        messages.error(request, "Seul un avoir brouillon peut être modifié.")
        return redirect(reverse("credit_note_detail", args=[note.id]) + _qs(company))
    form = CreditNoteForm(request.POST or None, instance=note, company=company)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Avoir mis à jour.")
        return redirect(reverse("credit_note_detail", args=[note.id]) + _qs(company))
    return render(request, "documents/credit_note_form.html", {
        "company": company, "form": form, "credit_note": note,
    })


@login_required
@require_POST
def credit_note_issue(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    note = _scoped(CreditNote, company, pk)
    issue_credit_note(note)
    messages.success(request, f"Avoir {note.number} émis.")
    return redirect(reverse("credit_note_detail", args=[note.id]) + _qs(company))


@login_required
@require_POST
def credit_note_delete(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    note = _scoped(CreditNote, company, pk)
    if note.status != "draft":
        messages.error(request, "Seul un avoir brouillon peut être supprimé.")
        return redirect(reverse("credit_note_detail", args=[note.id]) + _qs(company))
    note.delete()
    messages.success(request, "Avoir supprimé.")
    return redirect(reverse("credit_notes") + _qs(company))


# ---------------------------------------------------------------------------
# Paiements
# ---------------------------------------------------------------------------


@login_required
def payment_list(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    return render(request, "documents/payment_list.html", {
        "company": company,
        "payments": company.payments.select_related("invoice").all(),
    })


@login_required
def payment_create(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoice = None
    invoice_id = request.GET.get("facture")
    if invoice_id:
        invoice = company.invoices.filter(pk=invoice_id).first()
    form = PaymentForm(request.POST or None, company=company, invoice=invoice)
    if request.method == "POST" and form.is_valid():
        inv = form.cleaned_data["invoice"]
        if inv.company_id != company.id:
            messages.error(request, "Facture hors société.")
            return redirect(reverse("payments") + _qs(company))
        try:
            payment = register_payment(
                inv,
                amount=form.cleaned_data["amount"],
                method=form.cleaned_data["method"],
                paid_at=form.cleaned_data["paid_at"],
                reference=form.cleaned_data.get("reference") or "",
                notes=form.cleaned_data.get("notes") or "",
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return render(request, "documents/payment_form.html", {
                "company": company, "form": form,
            })
        messages.success(request, "Paiement enregistré.")
        return redirect(reverse("payment_detail", args=[payment.id]) + _qs(company))
    return render(request, "documents/payment_form.html", {"company": company, "form": form})


@login_required
def payment_detail(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    payment = _scoped(Payment, company, pk)
    return render(request, "documents/payment_detail.html", {
        "company": company, "payment": payment,
    })


@login_required
@require_POST
def payment_delete(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    payment = _scoped(Payment, company, pk)
    invoice = payment.invoice
    payment.delete()
    invoice.refresh_payment_status()
    messages.success(request, "Paiement supprimé.")
    return redirect(reverse("payments") + _qs(company))


# ---------------------------------------------------------------------------
# Import PDF
# ---------------------------------------------------------------------------


@login_required
def invoice_import_pdf(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    form = PdfImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["pdf_file"]
        try:
            data = upload.read()
            invoice, parsed = import_invoice_pdf(company, data, filename=upload.name)
        except PdfImportError as exc:
            messages.error(request, str(exc))
            return render(request, "documents/invoice_import.html", {
                "company": company, "form": form,
            })
        messages.success(
            request,
            "Facture importée en brouillon. Vérifiez les montants avant de l'émettre "
            "(aucun numéro de facture n'a été consommé).",
        )
        return redirect(reverse("invoice_detail", args=[invoice.id]) + _qs(company))
    return render(request, "documents/invoice_import.html", {
        "company": company, "form": form,
    })
