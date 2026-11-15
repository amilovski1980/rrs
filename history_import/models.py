"""Import intelligent d'historique : lots, documents et traçabilité.

Aucun document historique ne crée d'écriture comptable. L'import produit des
archives, ou des factures historiques marquées ``archived``/``historical_import``.
"""

import uuid
from decimal import Decimal

from django.db import models
from django.utils import timezone


def document_upload_path(instance, filename):
    return (
        f"history_import/{instance.company_id}/{instance.batch_id}/"
        f"{uuid.uuid4().hex[:10]}_{filename}"
    )


class ImportBatch(models.Model):
    """Un lot d'import : ajoutable, reprenable, avec progression."""

    STATUSES = [
        ("queued", "En attente"),
        ("processing", "Analyse en cours"),
        ("review", "À vérifier"),
        ("ready", "Prêt à importer"),
        ("done", "Terminé"),
        ("failed", "Erreur"),
    ]
    KIND_HINTS = [
        ("", "Détection automatique"),
        ("sale_invoice", "Factures de vente"),
        ("purchase_invoice", "Factures fournisseurs"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="import_batches"
    )
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="import_batches",
    )
    label = models.CharField(max_length=120, blank=True, verbose_name="Libellé")
    kind_hint = models.CharField(
        max_length=20, choices=KIND_HINTS, blank=True, default=""
    )
    status = models.CharField(max_length=12, choices=STATUSES, default="queued")
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Lot d'import d'historique"
        verbose_name_plural = "Lots d'import d'historique"
        ordering = ["-created_at"]

    def __str__(self):
        return self.label or f"Import du {self.created_at:%d/%m/%Y %H:%M}"

    @property
    def total(self):
        return self.documents.count()

    @property
    def processed_count(self):
        return self.documents.exclude(
            status__in=["queued", "processing"]
        ).count()

    @property
    def pending_count(self):
        return self.documents.filter(status__in=["queued", "processing"]).count()

    @property
    def progress_percent(self):
        total = self.total
        return round((self.processed_count / total) * 100) if total else 0


class ImportDocument(models.Model):
    """Un fichier du lot, avec extraction, statut et résultat d'import."""

    STATUSES = [
        ("queued", "En attente"),
        ("processing", "Analyse"),
        ("ready", "Prêt"),
        ("review", "À vérifier"),
        ("duplicate", "Doublon"),
        ("imported", "Importé"),
        ("error", "Erreur"),
        ("rejected", "Exclu"),
    ]
    KINDS = [
        ("sale_invoice", "Facture de vente"),
        ("purchase_invoice", "Facture fournisseur"),
        ("credit_note", "Avoir"),
        ("ticket", "Ticket / justificatif"),
        ("other", "Autre document"),
        ("unknown", "Non reconnu"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(
        ImportBatch, on_delete=models.CASCADE, related_name="documents"
    )
    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="import_documents"
    )
    file = models.FileField(upload_to=document_upload_path, max_length=255)
    file_data = models.BinaryField(
        null=True,
        blank=True,
        editable=False,
        verbose_name="Fichier en base",
    )
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=120, blank=True)
    size = models.PositiveIntegerField(default=0)
    checksum = models.CharField(max_length=64, db_index=True)
    status = models.CharField(max_length=12, choices=STATUSES, default="queued")
    kind = models.CharField(max_length=20, choices=KINDS, default="unknown")

    # Données extraites / corrigées
    seller_name = models.CharField(max_length=200, blank=True, verbose_name="Émetteur")
    seller_siret = models.CharField(max_length=20, blank=True)
    seller_vat = models.CharField(max_length=20, blank=True)
    customer_name = models.CharField(max_length=200, blank=True, verbose_name="Client")
    customer_siret = models.CharField(max_length=20, blank=True)
    customer_vat = models.CharField(max_length=20, blank=True)
    invoice_number = models.CharField(max_length=50, blank=True, verbose_name="N° facture")
    invoice_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    amount_ht = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal("0.00")
    )
    amount_vat = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal("0.00")
    )
    amount_ttc = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal("0.00")
    )
    vat_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("20.00")
    )
    currency = models.CharField(max_length=3, default="EUR")
    description = models.CharField(max_length=255, blank=True)

    extracted = models.JSONField(default=dict, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    raw_text = models.TextField(blank=True)
    error_message = models.TextField(blank=True)

    duplicate_of = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="duplicates",
    )
    duplicate_reason = models.CharField(max_length=255, blank=True)

    imported_invoice = models.ForeignKey(
        "documents.Invoice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="history_documents",
    )
    imported_purchase = models.ForeignKey(
        "purchases.PurchaseInvoice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="history_documents",
    )
    imported_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Document importé"
        verbose_name_plural = "Documents importés"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["batch", "status"]),
        ]

    def __str__(self):
        return self.original_name or f"Document {self.pk}"

    @property
    def is_actionable(self):
        return self.status in ("ready", "review")


class ImportAuditEvent(models.Model):
    """Journal d'audit du module (upload, analyse, correction, import)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="import_audit_events"
    )
    batch = models.ForeignKey(
        ImportBatch,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    document = models.ForeignKey(
        ImportDocument,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="import_audit_events",
    )
    action = models.CharField(max_length=40)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Événement d'import"
        verbose_name_plural = "Événements d'import"
        ordering = ["-created_at"]
