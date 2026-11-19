from decimal import Decimal, ROUND_HALF_UP

from .models import DepreciationSchedule

ZERO = Decimal('0.00')


def _annual_depreciation(asset):
    """Calculate the annual straight‑line depreciation amount for *asset*.
    Preference is given to *useful_life_years* if defined, otherwise the
    *depreciation_rate* (as a percentage) is used. Returns a Decimal.
    """
    if asset.useful_life_years and asset.useful_life_years > 0:
        amount = (asset.cost / asset.useful_life_years).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return amount
    if asset.depreciation_rate:
        rate = asset.depreciation_rate / Decimal('100')
        amount = (asset.cost * rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return amount
    return ZERO


def generate_depreciation_schedule(asset):
    """Generate a yearly DepreciationSchedule for *asset*.
    Existing schedule rows for the asset are removed before regeneration.
    The schedule runs from the acquisition year until the asset is fully
    depreciated (i.e. remaining amount reaches zero).
    Returns a list of created DepreciationSchedule instances.
    """
    # Delete any previous schedule for this asset
    asset.depreciation_schedule.all().delete()
    annual_amount = _annual_depreciation(asset)
    if annual_amount == ZERO:
        return []
    year = asset.acquisition_date.year
    remaining = asset.cost
    created = []
    while remaining > ZERO:
        amount = min(annual_amount, remaining)
        remaining -= amount
        accumulated = asset.cost - remaining
        schedule = DepreciationSchedule.objects.create(
            asset=asset,
            year=year,
            amount=amount,
            accumulated=accumulated,
            remaining=remaining,
        )
        created.append(schedule)
        year += 1
    return created
