import uuid
from decimal import Decimal

from django.db import models

from companies.models import Company


class Asset(models.Model):
    """Immobilisation d'une société.

    Fields:
        - company: société à laquelle appartient l'asset.
        - name: désignation de l'immobilisation.
        - description: texte libre.
        - acquisition_date: date d'achat ou de mise en service.
        - cost: valeur d'acquisition.
        - depreciation_rate: taux d'amortissement annuel en pourcentage (ex. 20 pour 20%).
        - useful_life_years: durée d'amortissement en années (si connue).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='assets')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    acquisition_date = models.DateField()
    cost = models.DecimalField(max_digits=15, decimal_places=2)
    depreciation_rate = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True,
        help_text='Taux d\'amortissement annuel en % (ex. 20.00 pour 20%).'
    )
    useful_life_years = models.PositiveIntegerField(
        blank=True, null=True,
        help_text='Durée d\'amortissement en années (facultatif, prioritaire sur le taux).'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='uniq_asset_per_company')
        ]
        ordering = ['-acquisition_date']

    def __str__(self):
        return f"{self.name} ({self.company})"


class DepreciationSchedule(models.Model):
    """Amortissement d'une immobilisation par année comptable."""

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='depreciation_schedule')
    year = models.PositiveIntegerField()
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    accumulated = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    remaining = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['asset', 'year'], name='uniq_depr_schedule_per_year')
        ]
        ordering = ['year']

    def __str__(self):
        return f"{self.asset.name} - {self.year}"