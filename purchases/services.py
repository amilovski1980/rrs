"""Écritures et cycle de vie des factures fournisseurs."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from accounting.models import ChartAccount, EntryLine, Journal, JournalEntry
from mailsync.matching import create_supplier, find_matching_supplier

from .models import PurchaseInvoice, SupplierPayment, PurchaseInvoiceLine
from assets.models import Asset
from assets.services import generate_depreciation_schedule

STEP = Decimal("0.01")


class PurchaseError(Exception):
    """Opération impossible sur une facture fournisseur."""


def resolve_account(company, code: str, *, label: str = "", roots: tuple = ()):
    """Compte exact, sinon plus proche racine, sinon création."""
    code = (code or "").strip().upper()
    if not code:
        return None
    account = ChartAccount.objects.filter(company=company, code=code).first()
    if account:
        return account
    for root in roots:
        account = (
            ChartAccount.objects.filter(company=company, code__startswith=root)
            .order_by("code")
            .first()
        )
        if account:
            return account
    return ChartAccount.objects.create(
        company=company, code=code, label=(label or code)[:100]
    )


def _entry(company, journal_code, label, reference, lines, on_date):
    existing = JournalEntry.objects.filter(
        company=company, reference=reference
    ).first()
    if existing:
        return existing
    journal = company.journals.filter(code=journal_code).first()
    if journal is None or any(account is None for account, _debit, _credit in lines):
        raise PurchaseError(f"Journal {journal_code} ou compte manquant.")
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
                entry=entry, account=account, debit=debit, credit=credit
            )
    return entry


@transaction.atomic
def post_purchase(invoice: PurchaseInvoice) -> JournalEntry:
    """Valide la facture et crée l'écriture ACH équilibrée (idempotent)."""
    if invoice.journal_entry_id:
        return invoice.journal_entry
    if invoice.status == "ignored":
        raise PurchaseError("Une facture ignorée ne peut pas être validée.")

    company = invoice.company
    journal = company.journals.filter(code="ACH").first()
    if journal is None:
        raise PurchaseError("Aucun journal ACH : générez le portail comptable.")

    # Resolve supplier (creation if missing)
    if invoice.supplier_id is None:
        supplier = find_matching_supplier(
            company, name=invoice.supplier_name or ""
        )
        if supplier is None:
            supplier = create_supplier(
                company,
                name=invoice.supplier_name or "Fournisseur",
                charge_code=invoice.charge_account_code,
            )
        invoice.supplier = supplier
    supplier = invoice.supplier
    if not invoice.supplier_name:
        invoice.supplier_name = supplier.name if supplier else "Fournisseur"

    # Resolve compte fournisseur (racine)
    supplier_account = resolve_account(
        company,
        invoice.supplier_account_root or "401",
        label="Fournisseurs",
        roots=("401",),
    )
    if supplier_account is None:
        raise PurchaseError("Plan comptable incomplet (compte fournisseur).")

    # Determine les lignes d'écriture à partir des lignes de facture ou, à défaut, des champs uniques
    entry_lines = []
    total_ht = Decimal("0.00")
    total_vat = Decimal("0.00")
    if invoice.lines.exists():
        for line in invoice.lines.all():
            # Charge
            charge_account = resolve_account(
                company,
                line.charge_account_code or "606000",
                label="Achats",
                roots=("606", "60"),
            )
            if charge_account is None:
                raise PurchaseError("Plan comptable incomplet (charge).")
            line_ht = (line.amount_ht or Decimal("0.00")).quantize(STEP)
            entry_lines.append((charge_account, line_ht, Decimal("0.00")))
            total_ht += line_ht
            # TVA
            if company.tva == "reel" and line.vat_rate and line.amount_vat > 0:
                vat_account = resolve_account(
                    company,
                    line.vat_account_code or "445660",
                    label="TVA déductible",
                    roots=("44566", "4456"),
                )
                if vat_account is None:
                    raise PurchaseError("Plan comptable incomplet (TVA).")
                line_vat = (line.amount_vat or Decimal("0.00")).quantize(STEP)
                entry_lines.append((vat_account, line_vat, Decimal("0.00")))
                total_vat += line_vat
            # Asset creation (simplified : tout compte commençant par "2" est considéré comme un bien)
            if line.charge_account_code and line.charge_account_code.upper().startswith("2"):
                asset = Asset.objects.create(
                    company=company,
                    name=line.description or f"Asset {line.id}",
                    description=line.description or "",
                    acquisition_date=invoice.invoice_date or timezone.localdate(),
                    cost=line.amount_ht,
                )
                generate_depreciation_schedule(asset)
    else:
        # Fallback aux champs uniques (compatibilité rétro‑active)
        charge = resolve_account(
            company,
            invoice.charge_account_code or "606000",
            label="Achats",
            roots=("606", "60"),
        )
        if charge is None:
            raise PurchaseError("Plan comptable incomplet (charge).")
        ht = (invoice.amount_ht or Decimal("0.00")).quantize(STEP)
        vat = Decimal("0.00")
        vat_account = None
        # For franchise regime, VAT is ignored; treat the total amount (TTC) as the expense amount.
        if company.tva == "reel":
            vat = (invoice.amount_vat or Decimal("0.00")).quantize(STEP)
            if vat > 0:
                vat_account = resolve_account(
                    company,
                    invoice.vat_account_code or "445660",
                    label="TVA déductible",
                    roots=("44566", "4456"),
                )
        ttc = (invoice.amount_ttc or Decimal("0.00")).quantize(STEP)
        # Validation des totaux
        if ht <= 0 and ttc > 0:
            ht = (ttc - vat).quantize(STEP)
        if ttc <= 0:
            ttc = (ht + vat).quantize(STEP)
        if company.tva == "franchise":
            # Ignore VAT difference; consider the whole TTC as the expense amount.
            ht = ttc
            vat = Decimal("0.00")
            vat_account = None
        if ht <= 0 or ttc <= 0:
            raise PurchaseError("Montants incomplets : renseignez HT et TTC.")
        if company.tva != "franchise" and abs((ht + vat) - ttc) > Decimal("0.02"):
            raise PurchaseError("HT + TVA n'est pas égal au TTC.")
        total_ht = ht
        total_vat = vat
        entry_lines.append((charge, ht, Decimal("0.00")))
        if vat_account is not None and vat > 0:
            entry_lines.append((vat_account, vat, Decimal("0.00")))
    total_ttc = (total_ht + total_vat).quantize(STEP)
    # Ajout du compte fournisseur (crédit)
    entry_lines.append((supplier_account, Decimal("0.00"), total_ttc))

    reference = (invoice.number or f"ACH-{invoice.id.hex[:8]}").strip()[:50]
    entry = _entry(
        company,
        "ACH",
        f"{invoice.supplier_name} — {invoice.number or 'facture'}",
        reference,
        entry_lines,
        invoice.invoice_date or timezone.localdate(),
    )

    invoice.journal_entry = entry
    invoice.amount_ht = total_ht
    invoice.amount_vat = total_vat
    invoice.amount_ttc = total_ttc
    invoice.status = "approved"
    invoice.save(
        update_fields=[
            "supplier",
            "supplier_name",
            "journal_entry",
            "amount_ht",
            "amount_vat",
            "amount_ttc",
            "status",
            "updated_at",
        ]
    )
    return entry


@transaction.atomic
def register_supplier_payment(
    invoice: PurchaseInvoice,
    amount,
    *,
    method: str = "transfer",
    paid_at=None,
    reference: str = "",
    notes: str = "",
    post_accounting: bool = True,
) -> SupplierPayment:
    """Enregistre un règlement (partiel ou total) au journal de banque."""
    if invoice.status == "ignored":
        raise PurchaseError("Cette facture est ignorée.")
    if invoice.status == "draft":
        post_purchase(invoice)
        invoice.refresh_from_db()

    amount = Decimal(str(amount)).quantize(STEP)
    if amount <= 0:
        raise PurchaseError("Le montant du règlement doit être positif.")
    if amount > invoice.amount_remaining + Decimal("0.01"):
        raise PurchaseError(
            f"Le règlement dépasse le reste à payer ({invoice.amount_remaining} €)."
        )

    paid_at = paid_at or timezone.localdate()
    company = invoice.company
    with transaction.atomic():
        payment = SupplierPayment.objects.create(
            company=company,
            invoice=invoice,
            amount=amount,
            method=method,
            paid_at=paid_at,
            reference=(reference or "")[:100],
            notes=(notes or "")[:255],
        )
        if post_accounting:
            entry = _entry(
                company,
                "BQ",
                f"Règlement {invoice.supplier_name} — {invoice.number or 'facture'}",
                (reference or f"{invoice.number or 'ACH'}-PAY-{payment.id.hex[:6]}")[:50],
                [
                    (
                        resolve_account(
                            company, invoice.supplier_account_root or "401", label="Fournisseurs", roots=("401",)
                        ),
                        amount,
                        Decimal("0.00"),
                    ),
                    (
                        resolve_account(company, "512", label="Banque", roots=("512",)),
                        Decimal("0.00"),
                        amount,
                    ),
                ],
                paid_at,
            )
            payment.journal_entry = entry
            payment.save(update_fields=["journal_entry"])
        invoice.refresh_payment_status()
    return payment


@transaction.atomic
def delete_supplier_payment(payment: SupplierPayment) -> None:
    """Supprime le règlement ET son écriture, puis recalcule le statut."""
    invoice = payment.invoice
    entry = payment.journal_entry
    payment.delete()
    if entry is not None:
        entry.delete()
    invoice.refresh_payment_status()
    if invoice.status == "paid" and invoice.amount_paid < invoice.amount_ttc:
        invoice.status = "approved"
        invoice.save(update_fields=["status", "updated_at"])


def record_mailsync_purchase(draft, entry, supplier):
    """Crée la fiche achats correspondant à un brouillon e-mail validé."""
    company = draft.company
    terms = (
        supplier.payment_terms_days
        if supplier is not None
        else (company.payment_terms_days or 30)
    )
    due_date = None
    if draft.invoice_date:
        due_date = draft.invoice_date + timedelta(days=terms or 30)
    defaults = {
        "company": company,
        "supplier": supplier,
        "supplier_name": (
            supplier.name if supplier is not None else draft.proposed_supplier_name
        )[:200],
        "number": (draft.invoice_number or "")[:50],
        "invoice_date": draft.invoice_date,
        "due_date": due_date,
        "amount_ht": draft.amount_ht,
        "amount_vat": draft.amount_vat,
        "amount_ttc": draft.amount_ttc,
        "vat_rate": draft.vat_rate,
        "charge_account_code": draft.charge_account_code or "606000",
        "vat_account_code": draft.vat_account_code or "445660",
        "supplier_account_root": draft.supplier_account_root or "401",
        "source": "mailsync",
        "status": "approved",
        "journal_entry": entry,
        "attachment_name": draft.attachment_name,
    }
    if draft.attachment:
        defaults["attachment"] = draft.attachment.name
    invoice, created = PurchaseInvoice.objects.get_or_create(
        mailsync_draft=draft, defaults=defaults
    )
    if not created and invoice.journal_entry_id is None:
        invoice.journal_entry = entry
        invoice.status = "approved"
        invoice.save(update_fields=["journal_entry", "status", "updated_at"])
    return invoice
