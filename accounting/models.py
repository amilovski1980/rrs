from decimal import Decimal
import uuid

from django.core.exceptions import ValidationError
from django.db import models

DEBIT = "debit"
CREDIT = "credit"


class ChartAccount(models.Model):
    """Compte du plan comptable genéral active pour une société."""

    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="accounts"
    )
    code = models.CharField(max_length=10)
    label = models.CharField(max_length=100)
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "code"], name="uniq_compte_par_societe"
            )
        ]
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.label}"


class Journal(models.Model):
    TYPES = [
        ("achats", "Achats"),
        ("ventes", "Ventes"),
        ("banque", "Banque"),
        ("caisse", "Caisse"),
        ("od", "Opérations diverses"),
    ]
    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="journals"
    )
    code = models.CharField(max_length=4, help_text="ACH, VEN, BQ, CA, OD")
    name = models.CharField(max_length=50)
    type = models.CharField(max_length=10, choices=TYPES)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "code"], name="uniq_journal_par_societe"
            )
        ]


class JournalEntry(models.Model):
    """Écriture équilibrée, saisie transactionnelle."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="entries"
    )
    journal = models.ForeignKey(Journal, on_delete=models.PROTECT, related_name="entries")
    date = models.DateField()
    label = models.CharField(max_length=200)
    reference = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    drafted_by_ai = models.BooleanField(default=False)
    validated = models.BooleanField(default=True)  # False = brouillon agent IA

    class Meta:
        ordering = ["date", "created_at"]
        indexes = [models.Index(fields=["company", "date"])]


class EntryLine(models.Model):
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(ChartAccount, on_delete=models.PROTECT)

    # Decimal systématiquement, jamais de float.
    debit = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    credit = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))

    def clean(self):
        self.debit = self.debit or 0
        self.credit = self.credit or 0
        d = self.debit
        c = self.credit
        if d > 0 and c > 0:
            raise ValidationError("Une ligne ne peut pas être débit et crédit à la fois.")
        if d < 0 or c < 0:
            raise ValidationError("Montants négatifs interdits.")

    def clean_balance(self):
        """Vérifie que l'écriture est équilibrée."""
        from django.db.models import Sum
        total = self.entry.lines.aggregate(
            d=Sum("debit"), c=Sum("credit")
        )
        if total["d"] != total["c"]:
            raise ValidationError("Écriture non équilibrée : debit != credit.")
