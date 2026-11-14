"""Registre des achats : factures fournisseurs et règlements.

Aucune écriture n'est créée à la saisie d'un brouillon. L'utilisateur
« valide » la facture, ce qui génère l'écriture ACH équilibrée, puis peut
enregistrer un ou plusieurs règlements (BQ 401/512).
"""

import uuid
from datetime import timedelta
from decimal import Decimal

from django.db import models
from django.utils import timezone

PAYMENT_METHODS = [
    ("transfer", "Virement"),
    ("card", "Carte"),
    ("check", "Chèque"),
    ("cash", "Espèces"),
    ("other", "Autre"),
]

STATUSES = [
    ("draft", "Brouillon"),
    ("approved", "À payer"),
    ("paid", "Payée"),
    ("ignored", "Ignorée"),
]

SOURCES = [
    ("manual", "Saisie manuelle"),
    ("mailsync", "Connecteur e-mail"),
    ("ticket", "Ticket de caisse"),
]


class PurchaseInvoice(models.Model):
    """Facture fournisseur (registre achats), indépendante de l'écriture."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="purchase_invoices"
    )
    supplier = models.ForeignKey(
        "mailsync.Supplier",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_invoices",
        verbose_name="Fournisseur",
    )
    supplier_name = models.CharField(
        max_length=200, blank=True, verbose_name="Nom du fournisseur"
    )
    number = models.CharField(max_length=50, blank=True, verbose_name="N° facture")
    invoice_date = models.DateField(null=True, blank=True, verbose_name="Date facture")
    due_date = models.DateField(null=True, blank=True, verbose_name="Date d'échéance")

    amount_ht = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"), verbose_name="Montant HT"
    )
    amount_vat = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"), verbose_name="TVA"
    )
    amount_ttc = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"), verbose_name="Montant TTC"
    )
    vat_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("20.00"), verbose_name="Taux TVA (%)"
    )

    charge_account_code = models.CharField(
        max_length=10, default="606000", verbose_name="Compte de charge"
    )
    vat_account_code = models.CharField(
        max_length=10, default="445660", verbose_name="Compte de TVA déductible"
    )
    supplier_account_root = models.CharField(
        max_length=10, default="401", verbose_name="Racine fournisseur"
    )

    description = models.CharField(max_length=255, blank=True, verbose_name="Libellé")
    status = models.CharField(max_length=12, choices=STATUSES, default="draft")
    source = models.CharField(max_length=12, choices=SOURCES, default="manual")

    mailsync_draft = models.ForeignKey(
        "mailsync.SupplierInvoiceDraft",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_invoices",
        verbose_name="Brouillon e-mail d'origine",
    )
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_invoices",
        verbose_name="Écriture comptable",
    )
    attachment = models.FileField(
        upload_to="purchases/justificatifs/",
        null=True,
        blank=True,
        verbose_name="Justificatif",
    )
    attachment_name = models.CharField(max_length=255, blank=True)

    notes = models.TextField(blank=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Facture fournisseur"
        verbose_name_plural = "Factures fournisseurs"
        ordering = ["-invoice_date", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "supplier", "number"],
                condition=~models.Q(number=""),
                name="uniq_achat_fournisseur_numero",
            )
        ]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["company", "due_date"]),
        ]

    def __str__(self):
        return f"{self.supplier_name or 'Fournisseur'} — {self.number or 'sans n°'}"

    @property
    def effective_due_date(self):
        terms = (
            self.supplier.payment_terms_days
            if self.supplier_id and self.supplier
            else (self.company.payment_terms_days or 30)
        )
        if self.due_date:
            return self.due_date
        if self.invoice_date:
            return self.invoice_date + timedelta(days=terms or 30)
        if self.created_at:
            return self.created_at.date() + timedelta(days=terms or 30)
        return None

    @property
    def is_late(self):
        due = self.effective_due_date
        return bool(
            self.status == "approved" and due and timezone.localdate() > due
        )

    @property
    def amount_paid(self):
        if not self.pk:
            return Decimal("0.00")
        total = self.payments.aggregate(total=models.Sum("amount"))["total"]
        return (total or Decimal("0.00")).quantize(Decimal("0.01"))

    @property
    def amount_remaining(self):
        remaining = (self.amount_ttc or Decimal("0.00")) - self.amount_paid
        return max(remaining, Decimal("0.00")).quantize(Decimal("0.01"))

    def refresh_payment_status(self):
        if self.status == "ignored":
            return
        if self.amount_paid >= (self.amount_ttc or Decimal("0.00")) and self.amount_ttc > 0:
            new_status = "paid"
        elif self.status != "draft":
            new_status = "approved"
        else:
            return
        if new_status != self.status:
            self.status = new_status
            self.save(update_fields=["status", "updated_at"])


class SupplierPayment(models.Model):
    """Règlement d'une facture fournisseur, avec son écriture BQ."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="supplier_payments"
    )
    invoice = models.ForeignKey(
        PurchaseInvoice, on_delete=models.CASCADE, related_name="payments"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Montant")
    method = models.CharField(
        max_length=20, choices=PAYMENT_METHODS, default="transfer", verbose_name="Mode"
    )
    paid_at = models.DateField(default=timezone.localdate, verbose_name="Date")
    reference = models.CharField(max_length=100, blank=True, verbose_name="Référence")
    notes = models.CharField(max_length=255, blank=True)
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supplier_payments",
        verbose_name="Écriture comptable",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Règlement fournisseur"
        verbose_name_plural = "Règlements fournisseurs"
        ordering = ["-paid_at", "-created_at"]

    def __str__(self):
        return f"{self.amount} € — {self.invoice}"
