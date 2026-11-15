import logging
import uuid
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import escape
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import get_valid_filename
from django.views.decorators.http import require_POST

from billing.access import UPGRADE_MESSAGE, feature_on
from companies.models import INVOICE_LAYOUTS, INVOICE_THEMES
from core.context import resolve_company

from .emailing import send_document_email
from .forms import (
    ClientForm,
    CreditNoteForm,
    InvoiceForm,
    InvoiceLineFormSet,
    PaymentForm,
    PdfImportForm,
    ProductForm,
    ProjectForm,
    QuoteForm,
    QuoteLineFormSet,
    TicketDeCaisseForm,
    TicketUploadForm,
)
from .einvoicing import (
    DEFAULT_PROFILE,
    EInvoicingError,
    build_facturx_pdf,
    generate_submission,
    submit_submission,
)
from .models import (
    Client,
    CreditNote,
    EInvoicingSubmission,
    Invoice,
    Payment,
    Product,
    Project,
    Quote,
    TicketDeCaisse,
    TICKET_CATEGORIES,
)
from .pdf import (
    first_page_png,
    render_credit_note_pdf,
    render_invoice_pdf,
    render_quote_pdf,
    render_sample_invoice_png,
)
from .pdf_import import PdfImportError, import_invoice_pdf
from .suggestions import product_suggestions
from .services import (
    convert_quote_to_invoice,
    delete_payment,
    issue_credit_note,
    issue_invoice,
    issue_quote_number,
    pay_invoice,
    recompute_invoice_totals_from_lines,
    recompute_quote_totals_from_lines,
    register_payment,
    sync_sale,
)

logger = logging.getLogger(__name__)


def _company_or_redirect(request):
    company = resolve_company(request)
    if company is None:
        return None, redirect("onboarding")
    return company, None


def _scoped(model, company, pk):
    return get_object_or_404(model, pk=pk, company=company)


def _pdf_response(request, number, payload):
    """Réponse PDF commune : forfait vérifié et nom de fichier assaini."""
    if not feature_on(request.user, "invoice_pdf"):
        raise PermissionDenied(UPGRADE_MESSAGE)
    filename = get_valid_filename(f"{number or 'document'}.pdf") or "document.pdf"
    response = HttpResponse(payload, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _preview_png_response(payload):
    response = HttpResponse(payload, content_type="image/png")
    response["Cache-Control"] = "private, max-age=60"
    return response


def _cached_preview(key, renderer):
    payload = cache.get(key)
    if payload:
        return payload
    try:
        payload = renderer()
    except Exception:
        logger.exception("Aperçu PDF indisponible (%s)", key)
        raise Http404("Aperçu indisponible.")
    cache.set(key, payload, 300)
    return payload


def _qs(company):
    return f"?societe={company.id}"


def _store_ticket_image(ticket, upload):
    """Stocke l'image sur disque, ou en base si le système de fichiers est read-only.

    Les fonctions Vercel ont un système de fichiers en lecture seule : sans ce
    repli, la sauvegarde d'un ticket importé par OCR renvoie une erreur 500.
    """
    if not upload:
        return
    content = upload.read()
    content_type = getattr(upload, "content_type", "") or ""
    try:
        upload.seek(0)
        ticket.image.save(upload.name or "ticket", ContentFile(content), save=False)
        ticket.image_data = None
        ticket.image_type = content_type
        ticket.save(update_fields=["image", "image_type", "image_data"])
    except OSError:
        ticket.image = ""
        ticket.image_data = content
        ticket.image_type = content_type
        ticket.save(update_fields=["image", "image_data", "image_type"])


# ---------------------------------------------------------------------------
# Factures (existant enrichi)
# ---------------------------------------------------------------------------


@login_required
def invoice_dashboard(request):
    """Synthèse facturation : KPI + raccourcis (rien n'est modifié ici)."""
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoices = list(company.invoices.all())
    zero = Decimal("0.00")

    def _sum_ttc(status_set):
        return sum((inv.amount_ttc for inv in invoices if inv.status in status_set), zero)

    ca_ttc = _sum_ttc({"issued", "received", "paid", "late"})
    open_amount = sum(
        (inv.amount_remaining for inv in invoices if inv.status in ("issued", "late", "received")),
        zero,
    )
    paid_ttc = _sum_ttc({"paid"})
    draft_count = sum(1 for inv in invoices if inv.status == "draft")
    issued_count = sum(1 for inv in invoices if inv.status in ("issued", "received", "late"))
    paid_count = sum(1 for inv in invoices if inv.status == "paid")
    late_count = sum(1 for inv in invoices if inv.status == "late")

    quotes = company.quotes.all()
    quote_count = quotes.count()
    quote_open = quotes.filter(status__in=("draft", "sent", "accepted")).count()
    credit_count = company.credit_notes.count()
    payment_count = company.payments.count()
    client_count = company.clients.count()
    tickets_qs = company.tickets_de_caisse.all()
    tickets_count = tickets_qs.count()
    tickets_ttc = sum((tk.montant_ttc for tk in tickets_qs), zero)

    recent = invoices[:8]
    return render(request, "documents/invoice_dashboard.html", {
        "company": company,
        "kpi": {
            "ca_ttc": ca_ttc,
            "open_amount": open_amount,
            "paid_ttc": paid_ttc,
            "draft_count": draft_count,
            "issued_count": issued_count,
            "paid_count": paid_count,
            "late_count": late_count,
            "invoice_count": len(invoices),
            "quote_count": quote_count,
            "quote_open": quote_open,
            "credit_count": credit_count,
            "payment_count": payment_count,
            "client_count": client_count,
            "tickets_count": tickets_count,
            "tickets_ttc": tickets_ttc,
        },
        "recent_invoices": recent,
    })


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


def _attach_or_autocreate_client(invoice, company, request):
    """Lier la fiche client existante ou la créer (drapeau du wizard Qonto)."""
    if invoice.client_id:
        return
    name = (invoice.client_name or "").strip()
    if len(name) < 2:
        return
    match = Client.objects.filter(company=company, name__iexact=name).first()
    if match is not None:
        invoice.client = match
        return
    if request.POST.get("client_autocreate") != "1":
        return
    siren = "".join(ch for ch in (invoice.client_siren or "") if ch.isdigit())[:9]
    client = Client.objects.create(
        company=company, name=name[:200], siren=siren if len(siren) == 9 else "",
    )
    invoice.client = client
    messages.success(
        request, f"Fiche client « {client.name} » créée automatiquement."
    )


@login_required
def invoice_preview_form(request):
    """Aperçu du document au fil du wizard de facture : rien n'est enregistré.

    Rend exactement le même article `.sheet` que la page finale, à partir des
    valeurs saisies dans le formulaire (client, dates et lignes).
    """
    company, bounce = _company_or_redirect(request)
    if bounce:
        return JsonResponse({"html": "", "error": "Aucune société."}, status=403)
    invoice = Invoice(company=company)
    form = InvoiceForm(request.POST or None, instance=invoice, company=company)
    formset = InvoiceLineFormSet(
        request.POST or None, instance=invoice, prefix="lines",
        form_kwargs={"company": company},
    )

    if form.is_valid():
        preview = form.save(commit=False)
        preview.company = company
    else:
        preview = invoice
    client_name = (preview.client_name or "").strip()
    client_siren = (preview.client_siren or "").strip()

    preview_lines = []
    vat_total = Decimal("0.00")
    ht_total = Decimal("0.00")
    vat_rate_main = Decimal("0.00")
    if formset.is_valid():
        for line_form in formset:
            cleaned = line_form.cleaned_data or {}
            if cleaned.get("DELETE"):
                continue
            description = (cleaned.get("description") or "").strip()
            if not description:
                continue
            quantity = cleaned.get("quantity")
            unit_price = cleaned.get("unit_price")
            vat_rate = cleaned.get("vat_rate")
            if isinstance(quantity, str) or quantity is None:
                try:
                    quantity = Decimal(str(quantity or "1.000").replace(",", "."))
                except InvalidOperation:
                    quantity = Decimal("1.000")
            if isinstance(unit_price, str) or unit_price is None:
                try:
                    unit_price = Decimal(str(unit_price or "0").replace(",", "."))
                except InvalidOperation:
                    unit_price = Decimal("0.00")
            if isinstance(vat_rate, str) or vat_rate is None:
                try:
                    vat_rate = Decimal(str(vat_rate or "0").replace(",", "."))
                except InvalidOperation:
                    vat_rate = Decimal("0.00")
            ht = (quantity * unit_price).quantize(Decimal("0.01"))
            vat_amount = (
                Decimal("0.00") if not vat_rate else (ht * vat_rate / Decimal("100")).quantize(Decimal("0.01"))
            )
            preview_lines.append({
                "description": description,
                "quantity": str(quantity.quantize(Decimal("0.001"))),
                "unit_price": unit_price,
                "vat_rate": vat_rate,
                "amount_ht": ht,
                "amount_ttc": (ht + vat_amount).quantize(Decimal("0.01")),
            })
            ht_total += ht
            vat_total += vat_amount
            if vat_amount > 0 and vat_rate > 0 and vat_rate_main == 0:
                vat_rate_main = vat_rate
    if ht_total > 0 and vat_total <= 0:
        vat_rate_main = Decimal("0.00")

    try:
        number = preview.number or f"BR-{uuid.uuid4().hex[:10]}"
    except AttributeError:
        number = f"BR-{uuid.uuid4().hex[:10]}"

    try:
        html = render_to_string(
            "documents/document_sheet.html",
            {
                "company": company,
                "invoice": preview,
                "kind_label": "Facture",
                "number": number,
                "status_label": "Brouillon",
                "created_at": timezone.now(),
                "client_name": client_name or "Client à préciser",
                "client_siren": client_siren,
                "amount_ht": ht_total.quantize(Decimal("0.01")),
                "vat_rate": vat_rate_main,
                "vat_amount": vat_total.quantize(Decimal("0.01")),
                "amount_ttc": (ht_total + vat_total).quantize(Decimal("0.01")),
                "lines": preview_lines,
                "client_kicker": "Facturé à",
                "foot_note": (
                    f"Payable à {preview.due_date|date:'d/m/Y'}."
                    if preview.due_date else "Payable à réception."
                ),
            },
            request=request,
        )
    except Exception:
        # Rien ne doit bloquer le wizard : en dernier recours un aperçu
        # simplifié est renvoyé à la place de l'erreur.
        html = (
            f"<article class='sheet sheet-azur'>"
            f"<h2 style='margin:0 0 6px'>{number} — Facture</h2>"
            f"<p style='margin:0 0 10px'><b>{escape(client_name) or 'Client à préciser'}</b>"
            f"{(' · SIREN ' + escape(client_siren)) if client_siren else ''}</p>"
            f"<p style='margin:0 0 10px'>{escape(preview_lines[0]['description'] if preview_lines else '')}</p>"
            f"<p style='font-size:18px;margin:12px 0 0'><b>"
            f"{(ht_total + vat_total).quantize(Decimal('0.01')).normalize()} € TTC</b> "
            f"<span style='font-size:12px'>(HT {ht_total.quantize(Decimal('0.01')).normalize()} · "
            f"TVA {vat_total.quantize(Decimal('0.01')).normalize()})</span></p>"
            f"</article>"
        )
    return JsonResponse({"html": html})


@login_required
@require_POST
def invoice_live_update(request):
    """Correction manuelle du brouillon depuis le panneau Aminia.

    Les valeurs envoyées écrasent client, SIREN, montant HT, TVA et
    désignation du brouillon courant, puis les totaux sont recalculés.
    """
    company, bounce = _company_or_redirect(request)
    if bounce:
        return JsonResponse({"error": "Aucune société."}, status=403)
    data = request.POST
    invoice_id = (data.get("invoice_id") or "").strip()
    invoice = (
        Invoice.objects.filter(pk=invoice_id, company=company).first()
        if invoice_id
        else None
    )
    if invoice is None:
        invoice = (
            Invoice.objects.filter(company=company, status="draft")
            .order_by("-created_at")
            .first()
        )
    if invoice is None:
        return JsonResponse({"error": "Aucun brouillon."}, status=404)

    changed = []
    client_name = (data.get("client_name") or "").strip()
    if client_name and client_name != (invoice.client_name or ""):
        invoice.client_name = client_name[:200]
        changed.append("client")
    siren = "".join(ch for ch in (data.get("client_siren") or "") if ch.isdigit())
    if siren and len(siren) == 9 and siren != (invoice.client_siren or ""):
        invoice.client_siren = siren
        changed.append("siren")
    vat_raw = (data.get("vat_rate") or "").strip()
    if vat_raw:
        try:
            vat_dec = Decimal(vat_raw.replace(",", ".")).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            vat_dec = None
        if vat_dec is not None and 0 <= vat_dec <= 100 and vat_dec != invoice.vat_rate:
            invoice.vat_rate = vat_dec
            changed.append("tva")
    amount_raw = (data.get("amount_ht") or "").strip()
    line = invoice.lines.first() if invoice.pk else None
    if amount_raw:
        try:
            ht = Decimal(amount_raw.replace(",", ".")).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            ht = None
        if ht is not None and line is not None and line.unit_price != ht:
            line.unit_price = ht
            line.save(update_fields=["unit_price", "updated_at"])
            changed.append("montant")
    designation = (data.get("designation") or "").strip()
    if designation:
        line = invoice.lines.first() if invoice.pk else None
        if line is not None and (line.description or "") != designation[:255]:
            line.description = designation[:255]
            line.save(update_fields=["description", "updated_at"])
            changed.append("prestation")

    invoice.save()
    from documents.services import recompute_invoice_totals_from_lines

    recompute_invoice_totals_from_lines(invoice)
    invoice.refresh_from_db()
    return JsonResponse({
        "ok": True,
        "changed": changed,
        "invoice": {
            "id": str(invoice.id),
            "number": invoice.number,
            "url": f"/factures/{invoice.id}/?societe={company.id}",
            "amount_ht": str(invoice.amount_ht),
            "vat_amount": str(invoice.vat_amount),
            "vat_rate": str(invoice.vat_rate),
            "amount_ttc": str(invoice.amount_ttc),
        },
    })


@login_required
def invoice_create(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    if request.method == "POST":
        from billing.access import invoice_create_block

        blocked = invoice_create_block(request.user)
        if blocked:
            messages.info(request, blocked)
            return redirect("plan_upgrade")
    invoice = Invoice(company=company)
    form = InvoiceForm(request.POST or None, instance=invoice, company=company)
    if not request.POST:
        # Préremplissage depuis le panneau de recherche Aminia.
        initial = {
            key: request.GET.get(key)
            for key in ("client_name", "client_siren")
            if request.GET.get(key)
        }
        if initial:
            form = InvoiceForm(initial=initial, instance=invoice, company=company)
    formset = InvoiceLineFormSet(
        request.POST or None,
        instance=invoice,
        prefix="lines",
        form_kwargs={"company": company},
    )
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            invoice = form.save(commit=False)
            invoice.company = company
            invoice.status = "draft"
            invoice.number = f"BR-{uuid.uuid4().hex[:10]}"
            invoice.amount_ht = Decimal("0.00")
            _attach_or_autocreate_client(invoice, company, request)
            invoice.save()
            formset.instance = invoice
            formset.save()
            recompute_invoice_totals_from_lines(invoice)
        messages.success(request, "Brouillon enregistré. Émettez la facture pour la numéroter.")
        return redirect(reverse("invoice_detail", args=[invoice.id]) + _qs(company))
    return render(request, "documents/invoice_form.html", {
        "company": company,
        "form": form,
        "formset": formset,
        "invoice": None,
    })


@login_required
def invoice_edit(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoice = _scoped(Invoice, company, pk)
    form = InvoiceForm(request.POST or None, instance=invoice, company=company)
    formset = InvoiceLineFormSet(
        request.POST or None,
        instance=invoice,
        prefix="lines",
        form_kwargs={"company": company},
    )
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            invoice = form.save()
            formset.instance = invoice
            formset.save()
            recompute_invoice_totals_from_lines(invoice)
        if invoice.status != "draft":
            sync_sale(invoice)
            messages.success(request, "Facture mise à jour. Les écritures liées ont été recalculées.")
        else:
            messages.success(request, "Brouillon mis à jour.")
        return redirect(reverse("invoice_detail", args=[invoice.id]) + _qs(company))
    return render(request, "documents/invoice_form.html", {
        "company": company,
        "form": form,
        "formset": formset,
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
        "layouts": INVOICE_LAYOUTS,
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
    return _pdf_response(request, invoice.number, payload)


@login_required
def invoice_preview_png(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoice = _scoped(Invoice, company, pk)
    key = (
        f"invoice-preview:{invoice.pk}:{company.invoice_theme}:"
        f"{company.invoice_layout}:{invoice.status}:{invoice.amount_ht}:"
        f"{invoice.lines.count()}:{bool(company.logo)}"
    )
    payload = _cached_preview(
        key, lambda: first_page_png(render_invoice_pdf(invoice, company))
    )
    return _preview_png_response(payload)


@login_required
def invoice_sample_preview_png(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    key = (
        f"invoice-sample-preview:{company.pk}:{company.invoice_theme}:"
        f"{company.invoice_layout}:{bool(company.logo)}"
    )
    payload = _cached_preview(key, lambda: render_sample_invoice_png(company))
    return _preview_png_response(payload)


@login_required
def invoice_einvoicing(request, pk):
    """Espace Factur-X : dernier dépôt, génération, transmission et téléchargements."""
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoice = _scoped(Invoice, company, pk)
    submission = invoice.einvoicing_submissions.first()
    from admin_backoffice.models import SiteConfiguration

    config = SiteConfiguration.objects.filter(pk=1).first()
    return render(request, "documents/einvoicing.html", {
        "company": company,
        "invoice": invoice,
        "submission": submission,
        "profiles": EInvoicingSubmission.PROFILES,
        "default_profile": getattr(config, "einvoicing_default_profile", DEFAULT_PROFILE),
        "enabled": bool(getattr(config, "einvoicing_enabled", False)),
        "provider": getattr(config, "einvoicing_provider", ""),
        "api_configured": bool((getattr(config, "einvoicing_api_url", "") or "").strip()),
    })


@login_required
@require_POST
def invoice_einvoicing_generate(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoice = _scoped(Invoice, company, pk)
    profile = request.POST.get("profile") or DEFAULT_PROFILE
    try:
        submission = generate_submission(invoice, profile=profile)
    except EInvoicingError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Factur-X généré ({submission.profile}) : {submission.reference}.")
    return redirect(reverse("invoice_einvoicing", args=[invoice.id]) + _qs(company))


@login_required
@require_POST
def invoice_einvoicing_submit(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoice = _scoped(Invoice, company, pk)
    submission = invoice.einvoicing_submissions.first()
    if submission is None:
        try:
            submission = generate_submission(invoice)
        except EInvoicingError as exc:
            messages.error(request, str(exc))
            return redirect(reverse("invoice_einvoicing", args=[invoice.id]) + _qs(company))
    try:
        submit_submission(submission)
    except EInvoicingError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Facture transmise à la plateforme électronique.")
    return redirect(reverse("invoice_einvoicing", args=[invoice.id]) + _qs(company))


@login_required
def invoice_einvoicing_xml(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoice = _scoped(Invoice, company, pk)
    submission = invoice.einvoicing_submissions.first()
    if submission is None:
        raise Http404("Aucune version Factur-X générée.")
    filename = get_valid_filename(f"{invoice.number}-factur-x.xml") or "factur-x.xml"
    response = HttpResponse(submission.xml_payload, content_type="application/xml; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def invoice_einvoicing_pdf(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoice = _scoped(Invoice, company, pk)
    submission = invoice.einvoicing_submissions.first()
    profile = submission.profile if submission else DEFAULT_PROFILE
    if not feature_on(request.user, "invoice_pdf"):
        raise PermissionDenied(UPGRADE_MESSAGE)
    payload = build_facturx_pdf(invoice, company, profile=profile)
    filename = get_valid_filename(f"{invoice.number}-factur-x.pdf") or "factur-x.pdf"
    response = HttpResponse(payload, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def quote_pdf(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    quote = _scoped(Quote, company, pk)
    payload = render_quote_pdf(quote, company)
    return _pdf_response(request, quote.number, payload)


@login_required
def quote_preview_png(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    quote = _scoped(Quote, company, pk)
    key = (
        f"quote-preview:{quote.pk}:{company.invoice_theme}:"
        f"{company.invoice_layout}:{quote.status}:{quote.amount_ht}:"
        f"{quote.lines.count()}:{bool(company.logo)}"
    )
    payload = _cached_preview(
        key, lambda: first_page_png(render_quote_pdf(quote, company))
    )
    return _preview_png_response(payload)


@login_required
def credit_note_pdf(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    note = _scoped(CreditNote, company, pk)
    payload = render_credit_note_pdf(note, company)
    return _pdf_response(request, note.number, payload)


@login_required
def credit_note_preview_png(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    note = _scoped(CreditNote, company, pk)
    key = (
        f"credit-note-preview:{note.pk}:{company.invoice_theme}:"
        f"{company.invoice_layout}:{note.amount_ht}:{bool(company.logo)}"
    )
    payload = _cached_preview(
        key, lambda: first_page_png(render_credit_note_pdf(note, company))
    )
    return _preview_png_response(payload)


def _email_document(request, company, document, kind: str, detail_name: str):
    """Envoi commun facture / devis / avoir, avec message de retour explicite."""
    if not feature_on(request.user, "invoice_pdf"):
        raise PermissionDenied(UPGRADE_MESSAGE)
    labels = {"invoice": "Facture", "quote": "Devis", "credit_note": "Avoir"}
    try:
        recipient = send_document_email(document, company, request.user, kind, request=request)
    except ValueError as exc:
        messages.error(request, str(exc))
    except Exception:
        logger.exception("Envoi email impossible pour %s", document.number)
        messages.error(
            request,
            "L'email n'a pas pu être envoyé. Vérifiez la configuration email puis réessayez.",
        )
    else:
        messages.success(
            request,
            f"{labels.get(kind, 'Document')} {document.number} envoyé à {recipient}.",
        )
    return redirect(reverse(detail_name, args=[document.id]) + _qs(company))


@login_required
@require_POST
def invoice_email(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    invoice = _scoped(Invoice, company, pk)
    return _email_document(request, company, invoice, "invoice", "invoice_detail")


@login_required
@require_POST
def quote_email(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    quote = _scoped(Quote, company, pk)
    return _email_document(request, company, quote, "quote", "quote_detail")


@login_required
@require_POST
def credit_note_email(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    note = _scoped(CreditNote, company, pk)
    return _email_document(request, company, note, "credit_note", "credit_note_detail")


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
def client_suggest(request):
    """Suggestions de fiches clients existantes (autocomplétion du wizard)."""
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    query = (request.GET.get("q") or "").strip()
    if len(query) < 2:
        return JsonResponse({"clients": []})
    clients = list(
        company.clients.filter(name__icontains=query).order_by("name")[:6]
        .values("id", "name", "siren", "address")
    )
    return JsonResponse({"clients": clients})


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
    if not request.POST:
        # Préremplissage depuis le panneau de recherche Aminia :
        # nom, SIREN, adresse, email et téléphone passés en query string.
        try:
            siren_digits = "".join(
                ch for ch in str(request.GET.get("siren") or "") if ch.isdigit()
            )[:9]
            initial = {
                key: request.GET.get(key)
                for key in ("name", "email", "phone", "address")
                if request.GET.get(key)
            }
            if siren_digits and len(siren_digits) == 9:
                initial["siren"] = siren_digits
            if initial:
                form = ClientForm(initial=initial, company=company)
        except Exception:
            pass
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
    return render(request, "documents/product_form.html", {
        "company": company,
        "form": form,
        "product_suggestions": product_suggestions(company),
    })


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
        "company": company,
        "form": form,
        "product": product,
        "product_suggestions": product_suggestions(company),
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
def quote_preview_form(request):
    """Aperçu du devis au fil du wizard : rien n'est enregistré."""
    company, bounce = _company_or_redirect(request)
    if bounce:
        return JsonResponse({"html": "", "error": "Aucune société."}, status=403)
    quote = Quote(company=company)
    form = QuoteForm(request.POST or None, instance=quote, company=company)
    formset = QuoteLineFormSet(
        request.POST or None, instance=quote, prefix="lines",
        form_kwargs={"company": company},
    )

    if form.is_valid():
        preview = form.save(commit=False)
        preview.company = company
    else:
        preview = quote
    client_name = (preview.client_name or "").strip()
    client_siren = (preview.client_siren or "").strip()

    preview_lines = []
    vat_total = Decimal("0.00")
    ht_total = Decimal("0.00")
    vat_rate_main = Decimal("0.00")
    if formset.is_valid():
        for line_form in formset:
            cleaned = line_form.cleaned_data or {}
            if cleaned.get("DELETE"):
                continue
            description = (cleaned.get("description") or "").strip()
            if not description:
                continue
            quantity = cleaned.get("quantity")
            unit_price = cleaned.get("unit_price")
            vat_rate = cleaned.get("vat_rate")
            if isinstance(quantity, str) or quantity is None:
                try:
                    quantity = Decimal(str(quantity or "1.000").replace(",", "."))
                except InvalidOperation:
                    quantity = Decimal("1.000")
            if isinstance(unit_price, str) or unit_price is None:
                try:
                    unit_price = Decimal(str(unit_price or "0").replace(",", "."))
                except InvalidOperation:
                    unit_price = Decimal("0.00")
            if isinstance(vat_rate, str) or vat_rate is None:
                try:
                    vat_rate = Decimal(str(vat_rate or "0").replace(",", "."))
                except InvalidOperation:
                    vat_rate = Decimal("0.00")
            ht = (quantity * unit_price).quantize(Decimal("0.01"))
            vat_amount = (
                Decimal("0.00") if not vat_rate else (ht * vat_rate / Decimal("100")).quantize(Decimal("0.01"))
            )
            preview_lines.append({
                "description": description,
                "quantity": str(quantity.quantize(Decimal("0.001"))),
                "unit_price": unit_price,
                "vat_rate": vat_rate,
                "amount_ht": ht,
                "amount_ttc": (ht + vat_amount).quantize(Decimal("0.01")),
            })
            ht_total += ht
            vat_total += vat_amount
            if vat_amount > 0 and vat_rate > 0 and vat_rate_main == 0:
                vat_rate_main = vat_rate
    if ht_total > 0 and vat_total <= 0:
        vat_rate_main = Decimal("0.00")

    try:
        html = render_to_string(
            "documents/document_sheet.html",
            {
                "company": company,
                "invoice": preview,
                "kind_label": "Devis",
                "number": getattr(preview, "number", "") or "DEV-………",
                "status_label": "",
                "created_at": timezone.now(),
                "client_name": client_name or "Client à préciser",
                "client_siren": client_siren,
                "amount_ht": ht_total.quantize(Decimal("0.01")),
                "vat_rate": vat_rate_main,
                "vat_amount": vat_total.quantize(Decimal("0.01")),
                "amount_ttc": (ht_total + vat_total).quantize(Decimal("0.01")),
                "lines": preview_lines,
                "client_kicker": "Devis pour",
                "foot_note": (
                    f"Devis valable jusqu'au {preview.due_date|date:'d/m/Y'}."
                    if preview.due_date else "Devis valable 30 jours."
                ),
            },
            request=request,
        )
    except Exception:
        # Même secours simplifié que pour la facture.
        html = (
            f"<article class='sheet sheet-azur'>"
            f"<h2 style='margin:0 0 6px'>Devis</h2>"
            f"<p style='margin:0 0 10px'><b>{escape(client_name) or 'Client à préciser'}</b></p>"
            f"<p style='margin:0 0 10px'>{escape(preview_lines[0]['description'] if preview_lines else '')}</p>"
            f"<p style='font-size:18px;margin:12px 0 0'><b>"
            f"{(ht_total + vat_total).quantize(Decimal('0.01')).normalize()} € TTC</b> "
            f"<span style='font-size:12px'>(HT {ht_total.quantize(Decimal('0.01')).normalize()} · "
            f"TVA {vat_total.quantize(Decimal('0.01')).normalize()})</span></p>"
            f"</article>"
        )
    return JsonResponse({"html": html})


@login_required
def quote_create(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    quote = Quote(company=company)
    form = QuoteForm(request.POST or None, instance=quote, company=company)
    if not request.POST:
        # Préremplissage depuis le panneau de recherche Aminia.
        initial = {
            key: request.GET.get(key)
            for key in ("client_name", "client_siren")
            if request.GET.get(key)
        }
        if initial:
            form = QuoteForm(initial=initial, instance=quote, company=company)
    formset = QuoteLineFormSet(
        request.POST or None,
        instance=quote,
        prefix="lines",
        form_kwargs={"company": company},
    )
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            quote = form.save(commit=False)
            quote.company = company
            quote.status = "draft"
            quote.number = f"BR-{uuid.uuid4().hex[:10]}"
            quote.amount_ht = Decimal("0.00")
            quote.vat_rate = Decimal("0.00")
            _attach_or_autocreate_client(quote, company, request)
            quote.save()
            formset.instance = quote
            formset.save()
            recompute_quote_totals_from_lines(quote)
        messages.success(request, "Devis enregistré en brouillon.")
        return redirect(reverse("quote_detail", args=[quote.id]) + _qs(company))
    return render(request, "documents/quote_form.html", {
        "company": company,
        "form": form,
        "formset": formset,
        "quote": None,
    })


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
    formset = QuoteLineFormSet(
        request.POST or None,
        instance=quote,
        prefix="lines",
        form_kwargs={"company": company},
    )
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            quote = form.save()
            formset.instance = quote
            formset.save()
            recompute_quote_totals_from_lines(quote)
        messages.success(request, "Devis mis à jour.")
        return redirect(reverse("quote_detail", args=[quote.id]) + _qs(company))
    return render(request, "documents/quote_form.html", {
        "company": company, "form": form, "formset": formset, "quote": quote,
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
    from billing.access import invoice_create_block

    blocked = invoice_create_block(request.user)
    if blocked:
        messages.info(request, blocked)
        return redirect("plan_upgrade")
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
    delete_payment(payment)
    messages.success(request, "Paiement supprimé et écriture de banque annulée.")
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

# ---------------------------------------------------------------------------
# Tickets de caisse (OCR + CRUD)
# ---------------------------------------------------------------------------
from datetime import datetime

from .receipt_ocr import (
    ReceiptOcrError,
    extract_receipt_text,
    parse_receipt_text,
    validate_upload,
)
from .receipt_services import propose_ticket_entry, validate_ticket


@login_required
def ticket_list(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    qs = company.tickets_de_caisse.all()
    date_from = (request.GET.get("du") or "").strip()
    date_to = (request.GET.get("au") or "").strip()
    categorie = (request.GET.get("categorie") or "").strip()
    fournisseur = (request.GET.get("fournisseur") or "").strip()
    statut = (request.GET.get("statut") or "").strip()

    if date_from:
        try:
            qs = qs.filter(date__gte=datetime.strptime(date_from, "%Y-%m-%d").date())
        except ValueError:
            messages.error(request, "Date de début invalide (AAAA-MM-JJ).")
    if date_to:
        try:
            qs = qs.filter(date__lte=datetime.strptime(date_to, "%Y-%m-%d").date())
        except ValueError:
            messages.error(request, "Date de fin invalide (AAAA-MM-JJ).")
    if categorie:
        qs = qs.filter(categorie=categorie)
    if fournisseur:
        qs = qs.filter(magasin__icontains=fournisseur)
    if statut:
        qs = qs.filter(statut=statut)

    tickets = list(qs)
    total_ttc = sum((tk.montant_ttc for tk in tickets), Decimal("0.00"))
    total_tva = sum((tk.montant_tva for tk in tickets), Decimal("0.00"))
    return render(request, "documents/ticket_list.html", {
        "company": company,
        "tickets": tickets,
        "total_ttc": total_ttc,
        "total_tva": total_tva,
        "categories": TICKET_CATEGORIES,
        "filters": {
            "du": date_from,
            "au": date_to,
            "categorie": categorie,
            "fournisseur": fournisseur,
            "statut": statut,
        },
    })


def _find_duplicate_ticket(company, parsed, amount):
    """Retourne un ticket proche (même date, montant et magasin) s'il existe."""
    if amount is None or amount <= 0:
        return None
    qs = TicketDeCaisse.objects.filter(company=company, montant_ttc=amount)
    day = parsed.get("date")
    if day:
        qs = qs.filter(date=day)
    store = (parsed.get("magasin") or "").strip()
    if store:
        qs = qs.filter(magasin__iexact=store)
    return qs.order_by("-created_at").first()


@login_required
def ticket_upload(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    form = TicketUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["fichier"]
        data = upload.read()
        upload.seek(0)
        try:
            validate_upload(upload.name, getattr(upload, "content_type", ""), upload.size)
            text = extract_receipt_text(
                data,
                filename=upload.name or "",
                content_type=getattr(upload, "content_type", "") or "",
            )
            parsed = parse_receipt_text(text)
        except ReceiptOcrError as exc:
            messages.error(request, str(exc))
            return render(request, "documents/ticket_upload.html", {
                "company": company,
                "form": form,
            })
        cat = form.cleaned_data.get("categorie") or parsed.get("categorie") or "autre"
        ttc = parsed.get("montant_ttc") or Decimal("0.00")
        tva = parsed.get("montant_tva") or Decimal("0.00")
        duplicate = _find_duplicate_ticket(company, parsed, ttc)
        ticket = TicketDeCaisse(
            company=company,
            date=parsed.get("date") or timezone.localdate(),
            magasin=parsed.get("magasin") or "",
            montant_ttc=ttc,
            montant_tva=tva,
            taux_tva=parsed.get("taux_tva") or Decimal("20.00"),
            categorie=cat,
            moyen_paiement=parsed.get("moyen_paiement") or "",
            statut="brouillon",
            ocr_text=text,
            line_items=parsed.get("line_items") or [],
        )
        ticket.save()
        _store_ticket_image(ticket, upload)
        # Propose draft entry (still brouillon / unvalidated)
        try:
            propose_ticket_entry(ticket)
        except ValueError as exc:
            messages.warning(request, f"Ticket créé, mais écriture non proposée : {exc}")
        if duplicate is not None:
            messages.warning(
                request,
                f"Doublon possible : un ticket de {duplicate.montant_ttc} € du "
                f"{duplicate.date:%d/%m/%Y} chez {duplicate.magasin or 'ce magasin'} "
                "existe déjà. Vérifiez avant de valider.",
            )
        messages.success(
            request,
            "Ticket importé par OCR. Vérifiez les montants puis validez.",
        )
        return redirect(reverse("ticket_detail", args=[ticket.id]) + _qs(company))
    return render(request, "documents/ticket_upload.html", {
        "company": company,
        "form": form,
    })


@login_required
def ticket_create(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    form = TicketDeCaisseForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data.get("image")
        ticket = form.save(commit=False)
        ticket.company = company
        if not ticket.statut:
            ticket.statut = "brouillon"
        if upload:
            ticket.image = None
        ticket.save()
        _store_ticket_image(ticket, upload)
        try:
            propose_ticket_entry(ticket)
        except ValueError:
            pass
        messages.success(request, "Ticket enregistré en brouillon.")
        return redirect(reverse("ticket_detail", args=[ticket.id]) + _qs(company))
    return render(request, "documents/ticket_form.html", {
        "company": company,
        "form": form,
        "ticket": None,
    })


@login_required
def ticket_detail(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    ticket = _scoped(TicketDeCaisse, company, pk)
    return render(request, "documents/ticket_detail.html", {
        "company": company,
        "ticket": ticket,
    })


@login_required
def ticket_image(request, pk):
    """Sert l'image du ticket, y compris quand elle est stockée en base."""
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    ticket = _scoped(TicketDeCaisse, company, pk)
    if ticket.image_data:
        response = HttpResponse(
            bytes(ticket.image_data),
            content_type=ticket.image_type or "application/octet-stream",
        )
        response["Content-Disposition"] = f'inline; filename="ticket-{ticket.id}"'
        return response
    if ticket.image:
        return redirect(ticket.image.url)
    raise Http404("Aucune image pour ce ticket.")


@login_required
def ticket_edit(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    ticket = _scoped(TicketDeCaisse, company, pk)
    form = TicketDeCaisseForm(request.POST or None, request.FILES or None, instance=ticket)
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data.get("image")
        if upload:
            form.instance.image = None
        ticket = form.save()
        _store_ticket_image(ticket, upload)
        if ticket.statut == "brouillon":
            try:
                # Recréer le brouillon si montants changés et ancienne non validée
                if ticket.journal_entry_id and not ticket.journal_entry.validated:
                    ticket.journal_entry.delete()
                    ticket.journal_entry = None
                    ticket.save(update_fields=["journal_entry"])
                propose_ticket_entry(ticket)
            except ValueError:
                pass
        messages.success(request, "Ticket mis à jour.")
        return redirect(reverse("ticket_detail", args=[ticket.id]) + _qs(company))
    return render(request, "documents/ticket_form.html", {
        "company": company,
        "form": form,
        "ticket": ticket,
    })


@login_required
@require_POST
def ticket_validate(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    ticket = _scoped(TicketDeCaisse, company, pk)
    try:
        validate_ticket(ticket)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect(reverse("ticket_detail", args=[ticket.id]) + _qs(company))
    messages.success(
        request,
        "Ticket validé. Une écriture brouillon a été proposée — confirmez-la "
        "dans la comptabilité avant passage au grand livre.",
    )
    return redirect(reverse("ticket_detail", args=[ticket.id]) + _qs(company))


@login_required
@require_POST
def ticket_post_entry(request, pk):
    """Valide au grand livre l'écriture brouillon proposée pour un ticket."""
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    ticket = _scoped(TicketDeCaisse, company, pk)
    entry = ticket.journal_entry
    if entry is None:
        messages.error(request, "Aucune écriture proposée pour ce ticket.")
    elif entry.validated:
        messages.info(request, "L'écriture est déjà validée.")
    else:
        entry.validated = True
        entry.save(update_fields=["validated"])
        messages.success(request, "Écriture validée au grand livre.")
    return redirect(reverse("ticket_detail", args=[ticket.id]) + _qs(company))


@login_required
@require_POST
def ticket_delete(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    ticket = _scoped(TicketDeCaisse, company, pk)
    if ticket.journal_entry_id and ticket.journal_entry and ticket.journal_entry.validated:
        messages.error(
            request,
            "Impossible de supprimer : l'écriture liée est déjà validée au grand livre.",
        )
        return redirect(reverse("ticket_detail", args=[ticket.id]) + _qs(company))
    if ticket.journal_entry_id and ticket.journal_entry and not ticket.journal_entry.validated:
        ticket.journal_entry.delete()
    ticket.delete()
    messages.success(request, "Ticket supprimé.")
    return redirect(reverse("tickets") + _qs(company))
