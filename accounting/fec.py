"""Export FEC (Fichier des Écritures Comptables) au format tabulé DGFiP."""

from __future__ import annotations

import csv
import io
from datetime import date

from django.utils import timezone

from .models import JournalEntry

FEC_COLUMNS = [
    "JournalCode",
    "JournalLib",
    "EcritureNum",
    "EcritureDate",
    "CompteNum",
    "CompteLib",
    "CompAuxNum",
    "CompAuxLib",
    "PieceRef",
    "PieceDate",
    "EcritureLib",
    "Debit",
    "Credit",
    "EcritureLet",
    "DateLet",
    "ValidDate",
    "Montantdevise",
    "Idevise",
]


def _money(value) -> str:
    """Montant FEC : deux décimales, séparateur virgule."""
    return f"{value or 0:.2f}".replace(".", ",")


def _date(value: date | None) -> str:
    return value.strftime("%Y%m%d") if value else ""


def build_fec(company, start: date, end: date) -> str:
    """Construit le FEC d'une société sur une période, écritures validées uniquement."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter="\t", lineterminator="\r\n")
    writer.writerow(FEC_COLUMNS)

    entries = (
        JournalEntry.objects.filter(
            company=company,
            validated=True,
            date__gte=start,
            date__lte=end,
        )
        .select_related("journal")
        .prefetch_related("lines__account")
        .order_by("date", "created_at")
    )

    for entry in entries:
        journal = entry.journal
        number = entry.pk.hex[:12].upper()
        valid_date = _date(
            timezone.localtime(entry.created_at).date() if entry.created_at else entry.date
        )
        for line in entry.lines.all():
            account = line.account
            writer.writerow(
                [
                    journal.code,
                    journal.name,
                    number,
                    _date(entry.date),
                    account.code,
                    account.label,
                    "",
                    "",
                    entry.reference,
                    _date(entry.date),
                    entry.label,
                    _money(line.debit),
                    _money(line.credit),
                    "",
                    "",
                    valid_date,
                    "",
                    "EUR",
                ]
            )
    return buffer.getvalue()
