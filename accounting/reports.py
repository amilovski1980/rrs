"""Chiffres du cockpit, de la balance et du grand livre. Écritures validées seulement."""
from datetime import date
from decimal import Decimal

from django.db.models import Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from .models import ChartAccount, EntryLine, JournalEntry

ZERO = Decimal("0.00")


def _money(value):
    return value if isinstance(value, Decimal) else (value or ZERO)


def _shift_month(year, month, delta):
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _spark_heights(values):
    """Hauteurs de 6 à 100 % pour dessiner une mini-tendance en CSS."""
    numbers = [float(value or 0) for value in values]
    if not numbers:
        return []
    low = min(0.0, min(numbers))
    high = max(0.0, max(numbers))
    span = high - low
    if span == 0:
        return [8] * len(numbers)
    return [max(6, min(100, round((value - low) / span * 100))) for value in numbers]


def _monthly_trends(company):
    """Six derniers mois : CA, TVA nette et solde clients 411."""
    today = timezone.localdate()
    months = []
    for delta in range(-5, 1):
        months.append(_shift_month(today.year, today.month, delta))
    window_start = date(months[0][0], months[0][1], 1)

    opening_clients = _money(
        EntryLine.objects.filter(
            entry__company=company,
            entry__validated=True,
            account__code__startswith="411",
            entry__date__lt=window_start,
        ).aggregate(total=Sum("debit") - Sum("credit"))["total"]
    )

    buckets = {
        key: {"revenue": ZERO, "vat_collected": ZERO, "vat_deductible": ZERO, "clients": ZERO}
        for key in months
    }
    aggregates = (
        EntryLine.objects.filter(
            entry__company=company,
            entry__validated=True,
            entry__date__gte=window_start,
        )
        .annotate(month=TruncMonth("entry__date"))
        .values("month", "account__code")
        .annotate(debit=Sum("debit"), credit=Sum("credit"))
    )
    for row in aggregates:
        month = row["month"]
        key = (month.year, month.month)
        bucket = buckets.get(key)
        if bucket is None:
            continue
        code = row["account__code"] or ""
        debit = _money(row["debit"])
        credit = _money(row["credit"])
        if code.startswith("7"):
            bucket["revenue"] += credit - debit
        elif code.startswith("44571"):
            bucket["vat_collected"] += credit - debit
        elif code.startswith("44566"):
            bucket["vat_deductible"] += debit - credit
        elif code.startswith("411"):
            bucket["clients"] += debit - credit

    revenue = [buckets[key]["revenue"] for key in months]
    vat_net = [
        buckets[key]["vat_collected"] - buckets[key]["vat_deductible"] for key in months
    ]
    clients = []
    running = opening_clients
    for key in months:
        running += buckets[key]["clients"]
        clients.append(running)
    return {
        "labels": [date(year, month, 1).strftime("%b") for year, month in months],
        "revenue": revenue,
        "vat_net": vat_net,
        "clients": clients,
        "revenue_spark": _spark_heights(revenue),
        "vat_spark": _spark_heights(vat_net),
        "clients_spark": _spark_heights(clients),
    }


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
        "trend": _monthly_trends(company),
    }
