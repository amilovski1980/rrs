import uuid
from decimal import Decimal

from django.db import models


class AnnualAccount(models.Model):
    """Comptes annuels d'une société pour une année donnée."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey('companies.Company', on_delete=models.CASCADE, related_name='annual_accounts')
    year = models.PositiveIntegerField()
    total_assets = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_liabilities = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_equity = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('company', 'year')
        ordering = ['-year']

    def __str__(self):
        return f"{self.company} - Exercice {self.year}"