"""Émission, encaissement, conversion devis et avoirs."""
from decimal import Decimal
import uuid

from django.db import transaction
from django.utils import timezone

from accounting.models import EntryLine, JournalEntry

from .models import (
    CreditNote,
    Invoice,
    InvoiceLine,
    Payment,
    Quote,
    QuoteLine,
    next_invoice_number,
)


def _account(company, code):
    return company.accounts.filter(code=code).first()


def _entry(company, journal_code, label, reference, lines, on_date):
    if JournalEntry.objects.filter(company=company, reference=reference).exists():
        return None
    journal = company.journals.filter(code=journal_code).first()
    if journal is None or any(account is None for account, _, _ in lines):
        return None
    with transaction.atomic():
        entry = JournalEntry.objects.create(
            company=company,
            journal=journal,
            date=on_date,
            label=label[:200],
            reference=reference[:50],
            validated=True,
        )
        for account, debit, credit in lines:
            EntryLine.objects.create(
                entry=entry,
                account=account,
                debit=debit,
                credit=credit,
            )
    return entry


def post_sale(invoice, on_date=None):
    """Écriture de vente 411 / 706 / 44571. Sans effet si elle existe déjà."""
    on_date = on_date or timezone.localdate()
    company = invoice.company
    ht = invoice.amount_ht
    vat = invoice.vat_amount
    ttc = invoice.amount_ttc
    sales = _account(company, "706") or _account(company, "701")
    lines = [(_account(company, "411"), ttc, Decimal("0.00"))]
    if vat > 0 and _account(company, "44571"):
        lines.append((sales, Decimal("0.00"), ht))
        lines.append((_account(company, "44571"), Decimal("0.00"), vat))
    else:
        lines.append((sales, Decimal("0.00"), ttc))
    return _entry(
        company,
        "VEN",
        f"Facture {invoice.number} — {invoice.client_name}",
        invoice.number,
        lines,
        on_date,
    )


def sync_sale(invoice):
    """Recalcule les écritures après modification, y compris si la facture est payée."""
    if invoice.status == "draft":
        return None
    company = invoice.company
    JournalEntry.objects.filter(company=company, reference=invoice.number).delete()
    JournalEntry.objects.filter(
        company=company, reference=f"{invoice.number}-REG"[:50]
    ).delete()
    posted = post_sale(invoice)
    if invoice.status == "paid":
        ttc = invoice.amount_ttc
        _entry(
            company,
            "BQ",
            f"Encaissement {invoice.number} — {invoice.client_name}",
            f"{invoice.number}-REG"[:50],
            [
                (_account(company, "512"), ttc, Decimal("0.00")),
                (_account(company, "411"), Decimal("0.00"), ttc),
            ],
            timezone.localdate(),
        )
    return posted


def issue_invoice(invoice):
    """Attribue le numéro définitif et passe la vente au journal."""
    if invoice.status != "draft":
        post_sale(invoice)
        return invoice
    today = timezone.localdate()
    invoice.number = next_invoice_number(invoice.company, today.year)
    invoice.status = "issued"
    invoice.save(update_fields=["number", "status"])
    post_sale(invoice, today)
    return invoice


def pay_invoice(invoice):
    """Passe la vente si besoin, puis l'encaissement 512 / 411 (paiement total)."""
    if invoice.status == "paid":
        return invoice
    if invoice.status == "draft":
        issue_invoice(invoice)
    else:
        post_sale(invoice)
    remaining = invoice.amount_remaining
    if remaining <= 0:
        remaining = invoice.amount_ttc
    today = timezone.localdate()
    register_payment(
        invoice,
        amount=remaining,
        method="transfer",
        paid_at=today,
        reference=f"{invoice.number}-REG",
        post_accounting=True,
    )
    return invoice


def register_payment(
    invoice,
    amount,
    method="transfer",
    paid_at=None,
    reference="",
    notes="",
    post_accounting=True,
):
    """Enregistre un paiement (partiel ou total) et met à jour le statut."""
    amount = Decimal(str(amount)).quantize(Decimal("0.01"))
    if amount <= 0:
        raise ValueError("Le montant du paiement doit être positif.")
    if invoice.status == "draft":
        raise ValueError("Impossible d'encaisser un brouillon : émettez la facture d'abord.")
    paid_at = paid_at or timezone.localdate()
    company = invoice.company
    with transaction.atomic():
        payment = Payment.objects.create(
            company=company,
            invoice=invoice,
            amount=amount,
            method=method,
            paid_at=paid_at,
            reference=(reference or "")[:100],
            notes=(notes or "")[:255],
        )
        if post_accounting:
            ref = (reference or f"{invoice.number}-P{payment.id.hex[:6]}")[:50]
            _entry(
                company,
                "BQ",
                f"Encaissement {invoice.number} — {invoice.client_name}",
                ref,
                [
                    (_account(company, "512"), amount, Decimal("0.00")),
                    (_account(company, "411"), Decimal("0.00"), amount),
                ],
                paid_at,
            )
        invoice.refresh_payment_status()
    return payment


def convert_quote_to_invoice(quote):
    """Convertit un devis en facture brouillon (numéro FAC consommé à l'émission)."""
    if quote.status == "converted" and quote.converted_invoice_id:
        return quote.converted_invoice
    if quote.status == "rejected":
        raise ValueError("Un devis refusé ne peut pas être converti.")
    company = quote.company
    with transaction.atomic():
        invoice = Invoice.objects.create(
            company=company,
            number=f"BR-{uuid.uuid4().hex[:10]}",
            client=quote.client,
            client_name=quote.client_name,
            client_siren=quote.client_siren,
            project=quote.project,
            amount_ht=quote.amount_ht,
            vat_rate=quote.vat_rate,
            status="draft",
        )
        for line in quote.lines.all():
            InvoiceLine.objects.create(
                invoice=invoice,
                product=line.product,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                vat_rate=line.vat_rate,
                position=line.position,
            )
        quote.converted_invoice = invoice
        quote.status = "converted"
        quote.save(update_fields=["converted_invoice", "status", "updated_at"])
    return invoice


def issue_credit_note(credit_note):
    """Attribue un numéro d'avoir (série AVO) sans trou."""
    if credit_note.status != "draft":
        return credit_note
    today = timezone.localdate()
    credit_note.number = next_invoice_number(credit_note.company, today.year, prefix="AVO")
    credit_note.status = "issued"
    credit_note.save(update_fields=["number", "status"])
    return credit_note


def issue_quote_number(quote):
    """Attribue un numéro de devis (série DEV) si encore temporaire."""
    if quote.number.startswith("BR-") or quote.number.startswith("DV-TMP"):
        today = timezone.localdate()
        quote.number = next_invoice_number(quote.company, today.year, prefix="DEV")
        if quote.status == "draft":
            quote.status = "sent"
            quote.save(update_fields=["number", "status", "updated_at"])
        else:
            quote.save(update_fields=["number", "updated_at"])
    return quote


def recompute_invoice_totals_from_lines(invoice):
    """Recalcule amount_ht / vat_rate à partir des lignes si présentes."""
    lines = list(invoice.lines.all())
    if not lines:
        return invoice
    total_ht = sum((line.amount_ht for line in lines), Decimal("0.00"))
    # Taux dominant (première ligne) — le modèle Invoice n'a qu'un taux global.
    invoice.amount_ht = total_ht
    invoice.vat_rate = lines[0].vat_rate
    invoice.save(update_fields=["amount_ht", "vat_rate"])
    return invoice
