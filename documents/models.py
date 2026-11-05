import uuid
from decimal import Decimal

from django.db import models
from django.db.models import Sum
from django.utils import timezone

# Mention facturation électronique (L.111-8 Code de commerce, arrêté 2026)
E_INVOICING_STATUSES = [
    ("draft", "Brouillon"),
    ("issued", "Émise"),
    ("received", "Réceptionnée (PA)"),
    ("paid", "Payée"),
    ("late", "En retard de paiement"),
]

QUOTE_STATUSES = [
    ("draft", "Brouillon"),
    ("sent", "Envoyé"),
    ("accepted", "Accepté"),
    ("converted", "Converti en facture"),
    ("rejected", "Refusé"),
    ("expired", "Expiré"),
]

CREDIT_NOTE_STATUSES = [
    ("draft", "Brouillon"),
    ("issued", "Émis"),
    ("applied", "Appliqué"),
]

PROJECT_STATUSES = [
    ("open", "Ouvert"),
    ("in_progress", "En cours"),
    ("done", "Terminé"),
    ("cancelled", "Annulé"),
]

PAYMENT_METHODS = [
    ("transfer", "Virement"),
    ("card", "Carte"),
    ("check", "Chèque"),
    ("cash", "Espèces"),
    ("other", "Autre"),
]


class Client(models.Model):
    """Client de la société (isolation multi-tenant)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="clients"
    )
    name = models.CharField(max_length=200, verbose_name="Nom")
    siren = models.CharField(max_length=9, blank=True, verbose_name="SIREN")
    address = models.CharField(max_length=255, blank=True, verbose_name="Adresse")
    email = models.EmailField(blank=True, verbose_name="E-mail")
    phone = models.CharField(max_length=30, blank=True, verbose_name="Téléphone")
    notes = models.TextField(blank=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Client"
        verbose_name_plural = "Clients"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "siren"],
                condition=~models.Q(siren=""),
                name="uniq_client_siren_per_company",
            ),
        ]

    def __str__(self):
        return self.name


class Product(models.Model):
    """Produit ou service réutilisable sur les lignes de facture / devis."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="products"
    )
    label = models.CharField(max_length=200, verbose_name="Libellé")
    description = models.TextField(blank=True, verbose_name="Description")
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"), verbose_name="Prix unitaire HT"
    )
    vat_rate = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("20.00"), verbose_name="Taux de TVA (%)"
    )
    unit = models.CharField(max_length=30, blank=True, default="unité", verbose_name="Unité")
    active = models.BooleanField(default=True, verbose_name="Actif")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["label"]
        verbose_name = "Produit / service"
        verbose_name_plural = "Produits / services"

    def __str__(self):
        return self.label


class Project(models.Model):
    """Projet pouvant être lié à des devis et factures."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="projects"
    )
    client = models.ForeignKey(
        Client, on_delete=models.SET_NULL, null=True, blank=True, related_name="projects"
    )
    name = models.CharField(max_length=200, verbose_name="Nom")
    description = models.TextField(blank=True, verbose_name="Description")
    status = models.CharField(
        max_length=20, choices=PROJECT_STATUSES, default="open", verbose_name="État"
    )
    start_date = models.DateField(null=True, blank=True, verbose_name="Début")
    end_date = models.DateField(null=True, blank=True, verbose_name="Fin")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Projet"
        verbose_name_plural = "Projets"

    def __str__(self):
        return self.name


class InvoiceSeries(models.Model):
    """Série de numérotation séquentielle sans trou par exercice et préfixe."""

    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="series"
    )
    prefix = models.CharField(max_length=10, default="FAC")
    year = models.PositiveIntegerField()
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "year", "prefix"], name="uniq_serie_annee_prefix"
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
    client = models.ForeignKey(
        Client,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
        verbose_name="Client (fiche)",
    )
    client_name = models.CharField(max_length=200)
    client_siren = models.CharField(max_length=9, blank=True)
    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
        verbose_name="Projet",
    )
    amount_ht = models.DecimalField(max_digits=12, decimal_places=2)
    vat_rate = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    status = models.CharField(max_length=12, choices=E_INVOICING_STATUSES, default="draft")
    file = models.FileField(upload_to="invoices/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.number

    @property
    def vat_amount(self):
        return (self.amount_ht * self.vat_rate / Decimal("100")).quantize(Decimal("0.01"))

    @property
    def amount_ttc(self):
        return (self.amount_ht + self.vat_amount).quantize(Decimal("0.01"))

    @property
    def amount_paid(self):
        total = self.payments.aggregate(s=Sum("amount"))["s"]
        return (total or Decimal("0.00")).quantize(Decimal("0.01"))

    @property
    def amount_remaining(self):
        rem = self.amount_ttc - self.amount_paid
        if rem < 0:
            return Decimal("0.00")
        return rem.quantize(Decimal("0.01"))

    def refresh_payment_status(self):
        """Met à jour le statut payé / émis selon les paiements enregistrés."""
        if self.status == "draft":
            return
        paid = self.amount_paid
        ttc = self.amount_ttc
        if paid <= 0:
            if self.status == "paid":
                self.status = "issued"
                self.save(update_fields=["status"])
            return
        if paid >= ttc:
            if self.status != "paid":
                self.status = "paid"
                self.save(update_fields=["status"])
        elif self.status == "paid":
            self.status = "issued"
            self.save(update_fields=["status"])


class InvoiceLine(models.Model):
    """Ligne de facture, éventuellement préremplie depuis le catalogue."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoice_lines",
        verbose_name="Produit / service",
    )
    description = models.CharField(max_length=255, verbose_name="Désignation")
    quantity = models.DecimalField(
        max_digits=12, decimal_places=3, default=Decimal("1.000"), verbose_name="Quantité"
    )
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"), verbose_name="Prix unitaire HT"
    )
    vat_rate = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("20.00"), verbose_name="TVA (%)"
    )
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "Ligne de facture"
        verbose_name_plural = "Lignes de facture"

    @property
    def amount_ht(self):
        return (self.quantity * self.unit_price).quantize(Decimal("0.01"))

    @property
    def vat_amount(self):
        return (self.amount_ht * self.vat_rate / Decimal("100")).quantize(Decimal("0.01"))

    @property
    def amount_ttc(self):
        return (self.amount_ht + self.vat_amount).quantize(Decimal("0.01"))


class Quote(models.Model):
    """Devis pouvant être converti en facture (numérotation séparée)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="quotes"
    )
    number = models.CharField(max_length=30, unique=True, editable=False)
    client = models.ForeignKey(
        Client, on_delete=models.SET_NULL, null=True, blank=True, related_name="quotes"
    )
    client_name = models.CharField(max_length=200)
    client_siren = models.CharField(max_length=9, blank=True)
    project = models.ForeignKey(
        Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="quotes"
    )
    amount_ht = models.DecimalField(max_digits=12, decimal_places=2)
    vat_rate = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    status = models.CharField(max_length=12, choices=QUOTE_STATUSES, default="draft")
    valid_until = models.DateField(null=True, blank=True, verbose_name="Valable jusqu'au")
    notes = models.TextField(blank=True)
    converted_invoice = models.OneToOneField(
        Invoice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_quote",
        verbose_name="Facture convertie",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Devis"
        verbose_name_plural = "Devis"

    def __str__(self):
        return self.number

    @property
    def vat_amount(self):
        return (self.amount_ht * self.vat_rate / Decimal("100")).quantize(Decimal("0.01"))

    @property
    def amount_ttc(self):
        return (self.amount_ht + self.vat_amount).quantize(Decimal("0.01"))


class QuoteLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(
        Product, on_delete=models.SET_NULL, null=True, blank=True, related_name="quote_lines"
    )
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("1.000"))
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    vat_rate = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("20.00"))
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]

    @property
    def amount_ht(self):
        return (self.quantity * self.unit_price).quantize(Decimal("0.01"))


class CreditNote(models.Model):
    """Avoir lié à une facture."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="credit_notes"
    )
    number = models.CharField(max_length=30, unique=True, editable=False)
    invoice = models.ForeignKey(
        Invoice, on_delete=models.PROTECT, related_name="credit_notes", verbose_name="Facture"
    )
    amount_ht = models.DecimalField(max_digits=12, decimal_places=2)
    vat_rate = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    reason = models.CharField(max_length=255, blank=True, verbose_name="Motif")
    status = models.CharField(max_length=12, choices=CREDIT_NOTE_STATUSES, default="draft")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Avoir"
        verbose_name_plural = "Avoirs"

    def __str__(self):
        return self.number

    @property
    def vat_amount(self):
        return (self.amount_ht * self.vat_rate / Decimal("100")).quantize(Decimal("0.01"))

    @property
    def amount_ttc(self):
        return (self.amount_ht + self.vat_amount).quantize(Decimal("0.01"))


class Payment(models.Model):
    """Paiement (partiel ou total) lié à une facture."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="payments"
    )
    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name="payments", verbose_name="Facture"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Montant")
    method = models.CharField(
        max_length=20, choices=PAYMENT_METHODS, default="transfer", verbose_name="Mode"
    )
    paid_at = models.DateField(default=timezone.localdate, verbose_name="Date")
    reference = models.CharField(max_length=100, blank=True, verbose_name="Référence")
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_at", "-created_at"]
        verbose_name = "Paiement"
        verbose_name_plural = "Paiements"

    def __str__(self):
        return f"{self.amount} € — {self.invoice.number}"
