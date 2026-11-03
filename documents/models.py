import uuid
from decimal import Decimal

from django.db import models

# Mention facturation électronique (L.111-8 Code de commerce, arrêté 2026)
E_INVOICING_STATUSES = [
    ("draft", "Brouillon"),
    ("issued", "Émise"),
    ("received", "Réceptionnée (PA)"),
    ("paid", "Payée"),
    ("late", "En retard de paiement"),
]


class InvoiceSeries(models.Model):
    """Série de numérotation séquentielle sans trou par exercice."""

    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="series"
    )
    prefix = models.CharField(max_length=10, default="FAC")
    year = models.PositiveIntegerField()
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "year"], name="uniq_serie_annee"
            )
        ]
        db_table = "documents_invoice_series"


def next_invoice_number(company, year, prefix="FAC"):
    """Numérotation atomique transactionnelle. Amende si trou => SELECT FOR UPDATE."""
    from django.db import transaction
    with transaction.atomic():
        series, _ = InvoiceSeries.objects.select_for_update().get_or_create(
            company=company, year=year, prefix=prefix
        )
        series.last_number += 1
        series.save(update_fields=["last_number"])
        return f"{prefix}-{year}-{series.last_number:05d}"


class Invoice(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="invoices"
    )
    number = models.CharField(max_length=30, unique=True, editable=False)
    client_name = models.CharField(max_length=200)
    client_siren = models.CharField(max_length=9, blank=True)
    amount_ht = models.DecimalField(max_digits=12, decimal_places=2)
    vat_rate = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    status = models.CharField(max_length=12, choices=E_INVOICING_STATUSES, default="draft")
    file = models.FileField(upload_to="invoices/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def vat_amount(self):
        return (self.amount_ht * self.vat_rate / Decimal("100")).quantize(Decimal("0.01"))

    @property
    def amount_ttc(self):
        return (self.amount_ht + self.vat_amount).quantize(Decimal("0.01"))

