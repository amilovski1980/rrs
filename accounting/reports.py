"""Chiffres du cockpit, de la balance et du grand livre. Écritures validées seulement."""
from decimal import Decimal

from django.db.models import Q, Sum

from .models import ChartAccount, JournalEntry

ZERO = Decimal("0.00")


def _money(value):
    return value if isinstance(value, Decimal) else (value or ZERO)


def balance_rows(company):
    validated = Q(entryline__entry__validated=True)
    accounts = (
        ChartAccount.objects.filter(company=company)
        .annotate(
            total_debit=Sum("entryline__debit", filter=validated),
            total_credit=Sum("entryline__credit", filter=validated),
        )
        .order_by("code")
    )
    rows = []
    total_debit = ZERO
    total_credit = ZERO
    for account in accounts:
        debit = _money(account.total_debit)
        credit = _money(account.total_credit)
        if debit == 0 and credit == 0:
            continue
        rows.append({
            "code": account.code,
            "label": account.label,
            "debit": debit,
            "credit": credit,
            "solde": debit - credit,
        })
        total_debit += debit
        total_credit += credit
    return rows, total_debit, total_credit


def cockpit_figures(company):
    rows, total_debit, total_credit = balance_rows(company)
    revenue = ZERO
    vat_collected = ZERO
    vat_deductible = ZERO
    clients = ZERO
    for row in rows:
        code = row["code"]
        if code.startswith("7"):
            revenue += row["credit"] - row["debit"]
        elif code.startswith("44571"):
            vat_collected += row["credit"] - row["debit"]
        elif code.startswith("44566"):
            vat_deductible += row["debit"] - row["credit"]
        elif code.startswith("411"):
            clients += row["solde"]
    entries = (
        JournalEntry.objects.filter(company=company, validated=True)
        .select_related("journal")
        .order_by("-date", "-created_at")[:6]
    )
    drafts = JournalEntry.objects.filter(company=company, validated=False).count()
    return {
        "revenue": revenue,
        "vat_net": vat_collected - vat_deductible,
        "clients": clients,
        "entries_count": JournalEntry.objects.filter(company=company, validated=True).count(),
        "drafts": drafts,
        "balanced": total_debit == total_credit,
        "recent_entries": entries,
    }
