from decimal import Decimal
from django.db import models

from assets.models import Asset
from accounting.models import ChartAccount, EntryLine
from .models import AnnualAccount

ZERO = Decimal('0.00')


def compute_annual_account(company, year):
    """Aggregate balances for *company* for the given *year* and create/update an AnnualAccount.
    Simplified implementation:
        - total_assets: sum of asset.cost.
        - total_liabilities: sum of chart accounts with code starting with '4' (typical liabilities) based on validated entries.
        - total_equity: total_assets - total_liabilities.
    """
    assets_total = Asset.objects.filter(company=company).aggregate(total=models.Sum('cost'))['total'] or ZERO

    # Liability accounts are those whose code starts with 4 (e.g., 401, 411, etc.)
    liabilities_qs = ChartAccount.objects.filter(company=company, code__startswith='4')
    liabilities_total = liabilities_qs.annotate(
        balance=models.Sum('entryline__debit') - models.Sum('entryline__credit')
    ).aggregate(total=models.Sum('balance'))['total'] or ZERO

    equity = assets_total - liabilities_total

    annual, created = AnnualAccount.objects.update_or_create(
        company=company,
        year=year,
        defaults={
            'total_assets': assets_total,
            'total_liabilities': liabilities_total,
            'total_equity': equity,
        }
    )
    return annual
