"""Émission et encaissement d'une facture, avec écriture équilibrée."""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from accounting.models import EntryLine, JournalEntry

from .models import next_invoice_number


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
    """Passe la vente si besoin, puis l'encaissement 512 / 411."""
    if invoice.status == "paid":
        return invoice
    if invoice.status == "draft":
        issue_invoice(invoice)
    else:
        post_sale(invoice)
    today = timezone.localdate()
    company = invoice.company
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
        today,
    )
    invoice.status = "paid"
    invoice.save(update_fields=["status"])
    return invoice

