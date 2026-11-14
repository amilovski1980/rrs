"""Schéma du connecteur e-mail comptable (Gmail aujourd'hui, Outlook demain).

Chaque table porte une FK ``company`` : l'isolation multi-tenant est
structurelle, comme dans le reste du projet (accounting, documents...).

Principes :
- les jetons OAuth2 sont stockés chiffrés (voir ``mailsync.crypto``) ;
- ``ProcessedEmail`` garantit l'anti-doublon via ``(config, message_id)`` ;
- ``SupplierInvoiceDraft`` est un brouillon : il ne touche jamais la
  comptabilité tant qu'un humain ne l'a pas validé.
"""

import uuid
from datetime import timedelta
from decimal import Decimal

from django.db import models
from django.utils import timezone


PROVIDER_CHOICES = [
    ("gmail", "Gmail"),
    ("outlook", "Outlook (bientôt)"),
]

FREQUENCY_CHOICES = [
    (15, "Toutes les 15 minutes"),
    (30, "Toutes les 30 minutes"),
    (60, "Toutes les heures"),
]

CONNECTION_STATUSES = [
    ("pending", "Non connecté"),
    ("connected", "Connecté"),
    ("error", "Erreur"),
]


class MailboxConfig(models.Model):
    """Paramétrage d'une boîte e-mail pour UNE société (relation 1:1).

    Une société = une boîte. Le jour où plusieurs boîtes seront nécessaires,
    il suffira de retirer la contrainte ``OneToOne`` : le reste du code
    manipule déjà ``config.pk`` et non ``company.mailbox_config``.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.OneToOneField(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="mailbox_config",
        verbose_name="Société",
    )
    provider = models.CharField(
        max_length=12, choices=PROVIDER_CHOICES, default="gmail", verbose_name="Fournisseur"
    )
    email_address = models.EmailField(blank=True, verbose_name="Adresse connectée")
    provider_account_id = models.CharField(max_length=120, blank=True)

    is_active = models.BooleanField(default=False, verbose_name="Synchronisation active")
    frequency_minutes = models.PositiveIntegerField(
        choices=FREQUENCY_CHOICES,
        default=30,
        verbose_name="Fréquence de vérification",
    )
    folder_label = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Libellé / dossier surveillé",
        help_text="Vide = toute la boîte de réception.",
    )

    # Paramètres comptables par défaut (surchargés au cas par cas sur le brouillon).
    journal = models.ForeignKey(
        "accounting.Journal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mailbox_configs",
        verbose_name="Journal par défaut",
    )
    charge_account_code = models.CharField(
        max_length=10, default="606000", verbose_name="Compte de charge par défaut"
    )
    vat_account_code = models.CharField(
        max_length=10, default="445660", verbose_name="Compte de TVA déductible"
    )
    supplier_account_root = models.CharField(
        max_length=10, default="401", verbose_name="Racine compte fournisseur"
    )

    # Jetons OAuth2 : jamais en clair (chiffrés Fernet, voir mailsync/crypto.py).
    access_token_enc = models.TextField(blank=True)
    refresh_token_enc = models.TextField(blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)
    granted_scopes = models.CharField(max_length=500, blank=True)

    status = models.CharField(
        max_length=12, choices=CONNECTION_STATUSES, default="pending", verbose_name="État"
    )
    last_sync_at = models.DateTimeField(null=True, blank=True, verbose_name="Dernière synchro")
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Connecteur e-mail"
        verbose_name_plural = "Connecteurs e-mail"

    def __str__(self):
        label = self.email_address or "boîte non connectée"
        return f"{self.company.denomination} — {label}"

    # ---- Jetons (chiffrement transparent) ---------------------------------
    def set_tokens(self, tokens):
        """Enregistre un ``OAuthTokens`` en chiffrant les secrets.

        ``tokens`` est duck-typé (access_token, refresh_token, expires_in,
        scope, email, account_id) pour éviter un import circulaire.
        """
        from .crypto import encrypt_text

        self.access_token_enc = encrypt_text(tokens.access_token)
        if getattr(tokens, "refresh_token", ""):
            self.refresh_token_enc = encrypt_text(tokens.refresh_token)
        expires_in = int(getattr(tokens, "expires_in", 0) or 0)
        if expires_in:
            self.token_expires_at = timezone.now() + timedelta(seconds=expires_in)
        if getattr(tokens, "scope", ""):
            self.granted_scopes = tokens.scope[:500]
        if getattr(tokens, "email", ""):
            self.email_address = tokens.email
        if getattr(tokens, "account_id", ""):
            self.provider_account_id = tokens.account_id

    def clear_tokens(self):
        self.access_token_enc = ""
        self.refresh_token_enc = ""
        self.token_expires_at = None
        self.granted_scopes = ""
        self.is_active = False
        self.status = "pending"
        self.last_error = ""

    @property
    def has_tokens(self) -> bool:
        return bool(self.access_token_enc or self.refresh_token_enc)


class ProcessedEmail(models.Model):
    """Journal des messages déjà vus : anti-doublon strict.

    La ligne est créée AVANT le parsing (``get_or_create``). Si un run
    précédent a laissé une erreur, le message est marqué ``error`` mais il
    ne sera jamais réimporté automatiquement : l'utilisateur peut relancer
    via l'écran de contrôle ou en supprimant la ligne.
    """

    STATUSES = [
        ("imported", "Importé"),
        ("skipped", "Ignoré"),
        ("error", "Erreur"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    config = models.ForeignKey(
        MailboxConfig, on_delete=models.CASCADE, related_name="processed_emails"
    )
    message_id = models.CharField(max_length=140, verbose_name="Identifiant fournisseur")
    subject = models.CharField(max_length=255, blank=True)
    from_email = models.CharField(max_length=254, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default="skipped")
    detail = models.CharField(max_length=255, blank=True)
    draft = models.ForeignKey(
        "SupplierInvoiceDraft",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_emails",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "E-mail traité"
        verbose_name_plural = "E-mails traités"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["config", "message_id"],
                name="uniq_email_traite_par_boite",
            )
        ]
        indexes = [models.Index(fields=["config", "created_at"])]

    def __str__(self):
        return f"{self.subject or self.message_id} ({self.get_status_display()})"


class Supplier(models.Model):
    """Fournisseur d'une société — entité qui manquait au projet.

    Rapprochement automatique : SIRET > TVA > domaine e-mail > nom.
    """

    ID_SOURCES = [
        ("manual", "Saisie manuelle"),
        ("mailsync", "Connecteur e-mail"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="suppliers"
    )
    name = models.CharField(max_length=200, verbose_name="Nom")
    siret = models.CharField(max_length=14, blank=True, verbose_name="SIRET")
    tva_intra = models.CharField(
        max_length=20, blank=True, verbose_name="TVA intracommunautaire"
    )
    email = models.CharField(max_length=254, blank=True, verbose_name="E-mail")
    email_domain = models.CharField(
        max_length=120,
        blank=True,
        help_text="Domaine de l'expéditeur, utilisé pour le rapprochement.",
    )
    phone = models.CharField(max_length=30, blank=True, verbose_name="Téléphone")
    contact_name = models.CharField(max_length=120, blank=True, verbose_name="Contact")
    address = models.CharField(max_length=255, blank=True, verbose_name="Adresse")
    iban = models.CharField(max_length=34, blank=True, verbose_name="IBAN")
    payment_terms_days = models.PositiveIntegerField(
        default=30, verbose_name="Délai de paiement (jours)"
    )
    is_active = models.BooleanField(default=True, verbose_name="Actif")
    default_charge_code = models.CharField(
        max_length=10,
        blank=True,
        verbose_name="Compte de charge préféré",
        help_text="Surcharge le compte par défaut de la société pour ce fournisseur.",
    )
    notes = models.TextField(blank=True)
    created_from = models.CharField(
        max_length=12, choices=ID_SOURCES, default="manual", verbose_name="Origine"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Fournisseur"
        verbose_name_plural = "Fournisseurs"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "siret"],
                condition=~models.Q(siret=""),
                name="uniq_fournisseur_siret_par_societe",
            ),
            models.UniqueConstraint(
                fields=["company", "tva_intra"],
                condition=~models.Q(tva_intra=""),
                name="uniq_fournisseur_tva_par_societe",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "email_domain"]),
            models.Index(fields=["company", "name"]),
        ]

    def __str__(self):
        return self.name


class SupplierInvoiceDraft(models.Model):
    """Facture fournisseur extraite d'un e-mail, en attente de validation.

    Aucun impact comptable tant que ``status != "validated"``. La validation
    crée une ``accounting.JournalEntry`` équilibrée et archive la pièce.
    """

    SOURCES = [
        ("facturx", "Factur-X (PDF hybride)"),
        ("ubl", "XML UBL"),
        ("cii", "XML CII"),
        ("pdf", "PDF (texte)"),
    ]
    STATUSES = [
        ("pending", "À valider"),
        ("validated", "Validée"),
        ("ignored", "Ignorée"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="invoice_drafts"
    )
    config = models.ForeignKey(
        MailboxConfig,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="drafts",
    )
    journal = models.ForeignKey(
        "accounting.Journal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoice_drafts",
        verbose_name="Journal",
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoice_drafts",
        verbose_name="Fournisseur",
    )

    # Données extraites (modifiables avant validation).
    proposed_supplier_name = models.CharField(
        max_length=200, blank=True, verbose_name="Fournisseur détecté"
    )
    supplier_siret = models.CharField(max_length=20, blank=True, verbose_name="SIRET")
    supplier_vat = models.CharField(max_length=20, blank=True, verbose_name="TVA")
    supplier_email = models.CharField(max_length=254, blank=True, verbose_name="E-mail expéditeur")
    invoice_number = models.CharField(max_length=50, blank=True, verbose_name="N° facture")
    invoice_date = models.DateField(null=True, blank=True, verbose_name="Date facture")

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

    # Paramètres comptables snapshotés à l'import (modifiables à l'écran).
    charge_account_code = models.CharField(
        max_length=10, blank=True, verbose_name="Compte de charge"
    )
    vat_account_code = models.CharField(max_length=10, blank=True, verbose_name="Compte de TVA")
    supplier_account_root = models.CharField(
        max_length=10, blank=True, verbose_name="Racine fournisseur"
    )

    source = models.CharField(max_length=12, choices=SOURCES, default="pdf")
    raw_text = models.TextField(blank=True, verbose_name="Texte extrait")
    attachment = models.FileField(
        upload_to="mailsync/justificatifs/",
        null=True,
        blank=True,
        verbose_name="Justificatif",
    )
    attachment_name = models.CharField(max_length=255, blank=True)

    status = models.CharField(max_length=12, choices=STATUSES, default="pending")
    entry = models.ForeignKey(
        "accounting.JournalEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoice_drafts",
        verbose_name="Écriture générée",
    )
    error_note = models.TextField(blank=True, verbose_name="Note d'erreur")
    created_at = models.DateTimeField(auto_now_add=True)
    validated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Brouillon de facture fournisseur"
        verbose_name_plural = "Brouillons de factures fournisseurs"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["company", "status"])]

    def __str__(self):
        return f"{self.proposed_supplier_name or 'Fournisseur'} — {self.invoice_number or 'sans n°'}"

    @property
    def is_pdf(self) -> bool:
        name = (self.attachment_name or "").lower()
        return name.endswith(".pdf")
