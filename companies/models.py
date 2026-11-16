import uuid

from django.conf import settings
from django.db import models

# Choix communs
ACTIVITIES = [
    ("btp", "BTP"),
    ("plomberie", "Plomberie"),
    ("electricite", "Électricité"),
    ("coiffure", "Coiffure"),
    ("resto", "Restauration"),
    ("artisan_autre", "Autre artisanat"),
]

REGIMES = [
    ("micro", "Micro-BIC"),
    ("reel_simple", "Réel simplifié"),
]

TVA_MODES = [
    ("franchise", "Franchise en base"),
    ("reel", "TVA (CA3/CA12)"),
]

SMTP_PROVIDERS = [
    ("gmail", "Gmail / Google Workspace"),
    ("outlook", "Outlook / Hotmail"),
    ("yahoo", "Yahoo Mail"),
    ("icloud", "iCloud Mail"),
    ("custom", "Nom de domaine personnel / autre SMTP"),
]

INVOICE_THEMES = [
    ("azur", "Azur"),
    ("carmin", "Carmin"),
    ("encre", "Encre"),
    ("sauge", "Sauge"),
    ("graphite", "Graphite"),
    ("indigo", "Indigo"),
    ("terra", "Terra"),
    ("vert", "Vert"),
    ("monochrome", "Noir et Blanc"),
]

INVOICE_LAYOUTS = [
    ("royal", "Royal Wave"),
    ("emerald", "Emerald Prestige"),
    ("imperial", "Noir & Or Impérial"),
    ("bordeaux", "Bordeaux & Champagne"),
    ("sapphire", "Saphir & Argent"),
    ("classique", "Classique"),
    ("minimal", "Minimal"),
    ("moderne", "Moderne"),
    ("compact", "Compact"),
]

INVOICE_LAYOUT_CODES = tuple(code for code, _label in INVOICE_LAYOUTS)

# Palette signature de chaque modèle : sélectionner un modèle applique sa
# couleur (l'utilisateur peut ensuite choisir une autre couleur librement).
INVOICE_LAYOUT_THEMES = {
    "royal": "azur",
    "emerald": "sauge",
    "imperial": "encre",
    "bordeaux": "carmin",
    "sapphire": "indigo",
}


class Company(models.Model):
    """Une société geree par un artisan. 1 tenant = 1 clientele = cette table."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="companies",
    )
    siren = models.CharField(max_length=9, unique=True)
    denomination = models.CharField(max_length=255)
    forme = models.CharField(max_length=10, default="SARL")
    address = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    # SMTP propre à la société : si renseigné, les factures/devis partent avec
    # ce serveur au lieu du SMTP global de la plateforme.
    smtp_provider = models.CharField(
        max_length=20,
        choices=SMTP_PROVIDERS,
        default="custom",
        verbose_name="Fournisseur e-mail",
    )
    smtp_host = models.CharField(max_length=255, blank=True, verbose_name="Serveur SMTP")
    smtp_port = models.PositiveIntegerField(default=587, verbose_name="Port SMTP")
    smtp_username = models.CharField(max_length=255, blank=True, verbose_name="Utilisateur SMTP")
    smtp_password = models.CharField(max_length=255, blank=True, verbose_name="Mot de passe SMTP")
    smtp_use_tls = models.BooleanField(default=True, verbose_name="SMTP avec TLS")
    smtp_from_email = models.EmailField(
        blank=True, verbose_name="Expéditeur des documents"
    )
    code_naf = models.CharField(max_length=10, blank=True)
    invoice_theme = models.CharField(
        max_length=12,
        choices=INVOICE_THEMES,
        default="azur",
        verbose_name="Couleur de facture",
    )
    invoice_layout = models.CharField(
        max_length=12,
        choices=INVOICE_LAYOUTS,
        blank=True,
        default="",
        verbose_name="Modèle de facture",
        help_text="Vide = mise en page automatique selon la couleur choisie.",
    )
    logo = models.BinaryField(null=True, blank=True)
    logo_type = models.CharField(max_length=40, blank=True)
    slogan = models.CharField(max_length=120, blank=True)
    tva_intra = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="TVA intracommunautaire",
        help_text="Vide = calculée automatiquement depuis le SIREN.",
    )

    # Coordonnées bancaires de la société, affichées sur les factures et devis.
    bank_name = models.CharField(max_length=120, blank=True, verbose_name="Banque")
    bank_iban = models.CharField(max_length=34, blank=True, verbose_name="IBAN")
    bank_bic = models.CharField(max_length=11, blank=True, verbose_name="BIC")

    # Profil repartition compta
    activites = models.JSONField(default=list, help_text="codes du questionnaire")
    regime = models.CharField(max_length=20, choices=REGIMES)
    tva = models.CharField(max_length=20, choices=TVA_MODES, default="franchise")
    exercice_debut = models.DateField(null=True, blank=True)
    payment_terms_days = models.PositiveIntegerField(
        default=30,
        verbose_name="Délai de paiement (jours)",
        help_text="Échéance par défaut des factures clients et fournisseurs.",
    )

    source_data = models.JSONField(
        default=dict, help_text="extrait RNE / KBIS importé brut, versionné"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(siren__regex=r"^\d{9}$"), name="siren_9_chiffres"
            )
        ]

    def __str__(self):
        return f"{self.denomination} ({self.siren})"

    @property
    def tva_intra_number(self) -> str:
        """Numéro de TVA saisi, extrait des données officielles, ou calculé depuis le SIREN."""
        from documents.vat import french_vat_from_siren, normalize_vat_number

        stored = normalize_vat_number(self.tva_intra)
        if stored:
            return stored
        data = self.source_data if isinstance(self.source_data, dict) else {}
        for key in ("tva_intra", "tva_number", "numero_tva", "vat_number"):
            candidate = normalize_vat_number(data.get(key))
            if candidate:
                return candidate
        return french_vat_from_siren(self.siren)


class KbisFile(models.Model):
    """Piece justificative << KBIS >> (extrait RNE depuis 2023)."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="kbis")
    file = models.FileField(upload_to="kbis/")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(
        max_length=20, choices=[("inpi", "INPI"), ("user", "utilisateur")],
        default="user",
    )
