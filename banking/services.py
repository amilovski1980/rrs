"""Import de relevés, rapprochement bancaire et création d'écritures."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from difflib import SequenceMatcher

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from accounting.models import ChartAccount, EntryLine, JournalEntry

from .models import BankAccount, BankRule, BankStatement, BankTransaction
from .parsers import parse_statement
from .utils import make_fingerprint, normalize_text

AUTO_MATCH_THRESHOLD = 55
DATE_WINDOW_DAYS = 7
STEP = Decimal("0.01")


class BankError(Exception):
    """Opération bancaire impossible."""


@dataclass
class ImportResult:
    statement: BankStatement
    parsed: int
    created: int
    duplicates: int
    matched: int

    def summary(self) -> str:
        parts = [f"{self.created} opération(s) importée(s)"]
        if self.duplicates:
            parts.append(f"{self.duplicates} doublon(s) ignoré(s)")
        parts.append(f"{self.matched} rapprochée(s) automatiquement")
        return " · ".join(parts)


def resolve_account(company, code: str, *, label: str = "", roots: tuple = ()):
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


def ensure_default_account(company) -> BankAccount:
    """Crée le compte principal depuis les coordonnées société si nécessaire."""
    existing = company.bank_accounts.first()
    if existing:
        return existing
    ledger = (
        company.accounts.filter(code__startswith="512").order_by("code").first()
    )
    journal = company.journals.filter(code="BQ").first()
    return BankAccount.objects.create(
        company=company,
        label="Compte principal",
        bank_name=company.bank_name,
        iban=company.bank_iban,
        bic=company.bank_bic,
        journal=journal,
        ledger_account=ledger,
    )


@transaction.atomic
def import_statement(account: BankAccount, data: bytes, filename: str = "") -> ImportResult:
    """Parse et importe un relevé, sans jamais créer deux fois la même ligne."""
    source_format, rows = parse_statement(data, filename)
    if not rows:
        raise BankError("Aucune opération dans le relevé.")
    dates = [row.date for row in rows]
    statement = BankStatement(
        company=account.company,
        account=account,
        date_start=min(dates),
        date_end=max(dates),
        original_filename=(filename or "")[:255],
        source_format=source_format,
        row_count=len(rows),
        content_hash=hashlib.sha256(data).hexdigest(),
    )
    if filename:
        statement.file.save(filename, ContentFile(data), save=False)
    statement.save()

    created = duplicates = matched = 0
    for row in rows:
        fingerprint = make_fingerprint(
            account.id, row.date, row.amount, row.label, row.external_id
        )
        bank_transaction, was_created = BankTransaction.objects.get_or_create(
            account=account,
            fingerprint=fingerprint,
            defaults={
                "company": account.company,
                "statement": statement,
                "date": row.date,
                "value_date": row.date,
                "label": row.label,
                "counterparty": row.counterparty,
                "reference": row.reference,
                "external_id": row.external_id,
                "amount": row.amount,
                "currency": account.currency,
            },
        )
        if not was_created:
            duplicates += 1
            continue
        created += 1
        if auto_match_transaction(bank_transaction) is not None:
            matched += 1

    return ImportResult(
        statement=statement,
        parsed=len(rows),
        created=created,
        duplicates=duplicates,
        matched=matched,
    )


def score_entry(bank_transaction: BankTransaction, entry: JournalEntry) -> int:
    days = abs((entry.date - bank_transaction.date).days)
    date_score = max(0, 25 - days * 3)
    transaction_text = normalize_text(
        f"{bank_transaction.label} {bank_transaction.counterparty} {bank_transaction.reference}"
    )
    entry_text = normalize_text(f"{entry.label} {entry.reference}")
    label_score = SequenceMatcher(None, transaction_text, entry_text).ratio() * 60
    reference_score = (
        15
        if entry.reference and normalize_text(entry.reference) in transaction_text
        else 0
    )
    return min(100, round(date_score + label_score + reference_score))


def candidate_entries(bank_transaction: BankTransaction):
    """Écritures de banque non rapprochées, montant identique, date proche."""
    ledger = bank_transaction.account.ledger
    if ledger is None:
        return []
    window_start = bank_transaction.date - timedelta(days=DATE_WINDOW_DAYS)
    window_end = bank_transaction.date + timedelta(days=DATE_WINDOW_DAYS)
    lines = EntryLine.objects.filter(
        entry__company=bank_transaction.company,
        entry__validated=True,
        account=ledger,
        entry__date__range=(window_start, window_end),
        entry__bank_transactions__isnull=True,
    )
    if bank_transaction.amount < 0:
        lines = lines.filter(credit=abs(bank_transaction.amount))
    else:
        lines = lines.filter(debit=bank_transaction.amount)

    entries = (
        JournalEntry.objects.filter(lines__in=lines)
        .distinct()
        .select_related("journal")
    )
    scored = [(entry, score_entry(bank_transaction, entry)) for entry in entries]
    return sorted(scored, key=lambda item: item[1], reverse=True)


def _apply_match(
    bank_transaction: BankTransaction,
    entry: JournalEntry,
    match_type: str,
    score: int = 0,
) -> None:
    if entry.company_id != bank_transaction.company_id:
        raise BankError("Écriture d'une autre société.")
    if not entry.validated:
        raise BankError("Une écriture brouillon ne peut pas être rapprochée.")
    other = BankTransaction.objects.filter(matched_entry=entry).exclude(
        pk=bank_transaction.pk
    )
    if other.exists():
        raise BankError("Cette écriture est déjà rapprochée d'une autre opération.")
    bank_transaction.matched_entry = entry
    bank_transaction.status = "matched"
    bank_transaction.match_type = match_type
    bank_transaction.match_score = score
    bank_transaction.save(
        update_fields=["matched_entry", "status", "match_type", "match_score"]
    )


def auto_match_transaction(bank_transaction: BankTransaction) -> JournalEntry | None:
    if bank_transaction.status != "unmatched":
        return bank_transaction.matched_entry
    candidates = candidate_entries(bank_transaction)
    if not candidates:
        return None
    entry, score = candidates[0]
    if score < AUTO_MATCH_THRESHOLD:
        return None
    _apply_match(bank_transaction, entry, "auto", score)
    return entry


def match_transaction(
    bank_transaction: BankTransaction, entry: JournalEntry
) -> None:
    """Rapprochement manuel : l'écriture doit mouvementer le compte 512."""
    ledger = bank_transaction.account.ledger
    if ledger is None:
        raise BankError("Aucun compte comptable 512 rattaché à ce compte bancaire.")
    lines = entry.lines.filter(account=ledger)
    if bank_transaction.amount < 0:
        lines = lines.filter(credit=abs(bank_transaction.amount))
    else:
        lines = lines.filter(debit=bank_transaction.amount)
    if not lines.exists():
        raise BankError(
            "L'écriture ne comporte pas le mouvement bancaire attendu "
            f"({bank_transaction.amount} € sur {ledger.code})."
        )
    _apply_match(bank_transaction, entry, "manual", score_entry(bank_transaction, entry))


def unmatch_transaction(bank_transaction: BankTransaction) -> None:
    bank_transaction.matched_entry = None
    bank_transaction.status = "unmatched"
    bank_transaction.match_type = ""
    bank_transaction.match_score = 0
    bank_transaction.save(
        update_fields=["matched_entry", "status", "match_type", "match_score"]
    )


@transaction.atomic
def create_entry_from_transaction(
    bank_transaction: BankTransaction,
    *,
    counterpart_code: str,
    vat_account_code: str = "",
    vat_amount: Decimal = Decimal("0.00"),
    label: str = "",
    reference: str = "",
    entry_date=None,
) -> JournalEntry:
    """Crée l'écriture de banque manquante (frais, virement, encaissement...)."""
    if bank_transaction.status == "matched":
        raise BankError("Cette opération est déjà rapprochée.")
    company = bank_transaction.company
    ledger = bank_transaction.account.ledger
    if ledger is None:
        ledger = resolve_account(company, "512", label="Banque", roots=("512",))
        bank_transaction.account.ledger_account = ledger
        bank_transaction.account.save(update_fields=["ledger_account"])
    journal = bank_transaction.account.journal or company.journals.filter(
        code="BQ"
    ).first()
    if journal is None:
        raise BankError("Aucun journal de banque (BQ) pour cette société.")

    counterpart = resolve_account(
        company, counterpart_code, label="Contrepartie bancaire"
    )
    if counterpart is None:
        raise BankError("Compte de contrepartie manquant.")

    amount = bank_transaction.absolute_amount
    vat = Decimal(str(vat_amount or 0)).quantize(STEP)
    if vat < 0:
        vat = Decimal("0.00")
    if vat > amount:
        vat = amount
    vat_account = None
    if vat > 0:
        vat_account = resolve_account(
            company,
            vat_account_code or "445660",
            label="TVA déductible",
            roots=("44566", "4456"),
        )

    entry_label = (label or bank_transaction.label or "Opération bancaire")[:200]
    entry_reference = (
        reference
        or bank_transaction.reference
        or f"BQ-{bank_transaction.id.hex[:10]}"
    )[:50]

    with transaction.atomic():
        entry = JournalEntry.objects.create(
            company=company,
            journal=journal,
            date=entry_date or bank_transaction.date,
            label=entry_label,
            reference=entry_reference,
            validated=True,
        )
        if bank_transaction.amount < 0:
            net = (amount - vat).quantize(STEP)
            EntryLine.objects.create(
                entry=entry, account=counterpart, debit=net, credit=Decimal("0.00")
            )
            if vat_account is not None and vat > 0:
                EntryLine.objects.create(
                    entry=entry,
                    account=vat_account,
                    debit=vat,
                    credit=Decimal("0.00"),
                )
            EntryLine.objects.create(
                entry=entry,
                account=ledger,
                debit=Decimal("0.00"),
                credit=amount,
            )
        else:
            EntryLine.objects.create(
                entry=entry,
                account=ledger,
                debit=amount,
                credit=Decimal("0.00"),
            )
            EntryLine.objects.create(
                entry=entry,
                account=counterpart,
                debit=Decimal("0.00"),
                credit=amount,
            )
        _apply_match(bank_transaction, entry, "entry", 100)
    return entry


def find_rule(bank_transaction: BankTransaction) -> BankRule | None:
    rules = BankRule.objects.filter(company=bank_transaction.company).select_related(
        "counterpart_account"
    )
    for rule in rules:
        if rule.matches(bank_transaction):
            return rule
    return None


def accounting_balance(account: BankAccount) -> Decimal:
    ledger = account.ledger
    if ledger is None:
        return Decimal("0.00")
    totals = EntryLine.objects.filter(
        entry__company=account.company,
        entry__validated=True,
        account=ledger,
    ).aggregate(debit=Sum("debit"), credit=Sum("credit"))
    return (
        (totals["debit"] or Decimal("0.00"))
        - (totals["credit"] or Decimal("0.00"))
    ).quantize(STEP)
