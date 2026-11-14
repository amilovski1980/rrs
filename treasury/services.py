"""Position de trésorerie et prévisionnel, calculés depuis la comptabilité."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from accounting.models import EntryLine
from banking.models import BankTransaction
from banking.services import accounting_balance
from documents.models import Invoice
from purchases.models import PurchaseInvoice

ZERO = Decimal("0.00")
FORECAST_WEEKS = 13


def _money(value) -> Decimal:
    return (value or ZERO).quantize(Decimal("0.01"))


def _lines_balance(company, code_prefix: str) -> Decimal:
    totals = EntryLine.objects.filter(
        entry__company=company,
        entry__validated=True,
        account__code__startswith=code_prefix,
    ).aggregate(debit=Sum("debit"), credit=Sum("credit"))
    return _money((totals["debit"] or ZERO) - (totals["credit"] or ZERO))


def _open_receivables(company):
    invoices = (
        Invoice.objects.filter(
            company=company, status__in=["issued", "late", "received"]
        )
        .select_related("client")
        .prefetch_related("payments")
    )
    return [invoice for invoice in invoices if invoice.amount_remaining > ZERO]


def _open_payables(company):
    invoices = (
        PurchaseInvoice.objects.filter(company=company, status="approved")
        .select_related("supplier")
        .prefetch_related("payments")
    )
    return [invoice for invoice in invoices if invoice.amount_remaining > ZERO]


def _aging(items) -> dict:
    today = timezone.localdate()
    buckets = {
        "current": ZERO,
        "d1_30": ZERO,
        "d31_60": ZERO,
        "d60": ZERO,
    }
    for item in items:
        remaining = item.amount_remaining
        due = item.effective_due_date
        if due is None or due >= today:
            buckets["current"] += remaining
            continue
        days = (today - due).days
        if days <= 30:
            buckets["d1_30"] += remaining
        elif days <= 60:
            buckets["d31_60"] += remaining
        else:
            buckets["d60"] += remaining
    return {key: _money(value) for key, value in buckets.items()}


@dataclass
class Forecast:
    weeks: list = field(default_factory=list)
    beyond_in: Decimal = ZERO
    beyond_out: Decimal = ZERO
    total_in: Decimal = ZERO
    total_out: Decimal = ZERO


def _forecast(position: Decimal, receivables, payables) -> Forecast:
    today = timezone.localdate()
    week_start = today - timedelta(days=today.weekday())
    buckets = []
    for index in range(FORECAST_WEEKS):
        start = week_start + timedelta(days=7 * index)
        buckets.append(
            {
                "start": start,
                "label": start.strftime("%d/%m"),
                "inflow": ZERO,
                "outflow": ZERO,
            }
        )

    beyond_in = beyond_out = ZERO
    for invoice in receivables:
        due = invoice.effective_due_date or today
        index = max(0, (due - week_start).days // 7)
        if index >= FORECAST_WEEKS:
            beyond_in += invoice.amount_remaining
        else:
            buckets[index]["inflow"] += invoice.amount_remaining
    for invoice in payables:
        due = invoice.effective_due_date or today
        index = max(0, (due - week_start).days // 7)
        if index >= FORECAST_WEEKS:
            beyond_out += invoice.amount_remaining
        else:
            buckets[index]["outflow"] += invoice.amount_remaining

    running = position
    for bucket in buckets:
        bucket["inflow"] = _money(bucket["inflow"])
        bucket["outflow"] = _money(bucket["outflow"])
        bucket["net"] = _money(bucket["inflow"] - bucket["outflow"])
        running = _money(running + bucket["net"])
        bucket["balance"] = running

    return Forecast(
        weeks=buckets,
        beyond_in=_money(beyond_in),
        beyond_out=_money(beyond_out),
        total_in=_money(sum((bucket["inflow"] for bucket in buckets), ZERO)),
        total_out=_money(sum((bucket["outflow"] for bucket in buckets), ZERO)),
    )


@dataclass
class TreasurySnapshot:
    position: Decimal
    bank_statement_balance: Decimal
    bank_accounting_balance: Decimal
    cash_balance: Decimal
    receivables_total: Decimal
    payables_total: Decimal
    net_position: Decimal
    overdue_receivables: int
    overdue_payables: int
    unmatched_bank: int
    accounts: list
    receivables: list
    payables: list
    receivables_aging: dict
    payables_aging: dict
    forecast: Forecast


def build_snapshot(company) -> TreasurySnapshot:
    accounts = list(company.bank_accounts.filter(is_active=True))
    statement_balance = _money(sum((account.balance for account in accounts), ZERO))
    bank_accounting = _lines_balance(company, "512")
    cash = _lines_balance(company, "530")
    position = _money(bank_accounting + cash)

    receivables = _open_receivables(company)
    payables = _open_payables(company)
    receivables_total = _money(sum((item.amount_remaining for item in receivables), ZERO))
    payables_total = _money(sum((item.amount_remaining for item in payables), ZERO))

    today = timezone.localdate()
    return TreasurySnapshot(
        position=position,
        bank_statement_balance=statement_balance,
        bank_accounting_balance=bank_accounting,
        cash_balance=cash,
        receivables_total=receivables_total,
        payables_total=payables_total,
        net_position=_money(position + receivables_total - payables_total),
        overdue_receivables=sum(
            1
            for item in receivables
            if item.effective_due_date and item.effective_due_date < today
        ),
        overdue_payables=sum(
            1
            for item in payables
            if item.effective_due_date and item.effective_due_date < today
        ),
        unmatched_bank=BankTransaction.objects.filter(
            company=company, status="unmatched"
        ).count(),
        accounts=[
            {
                "account": account,
                "statement_balance": account.balance,
                "accounting_balance": accounting_balance(account),
            }
            for account in accounts
        ],
        receivables=sorted(
            receivables,
            key=lambda item: item.effective_due_date or date.max,
        )[:10],
        payables=sorted(
            payables,
            key=lambda item: item.effective_due_date or date.max,
        )[:10],
        receivables_aging=_aging(receivables),
        payables_aging=_aging(payables),
        forecast=_forecast(position, receivables, payables),
    )
