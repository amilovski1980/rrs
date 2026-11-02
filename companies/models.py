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
    code_naf = models.CharField(max_length=10, blank=True)

    # Profil repartition compta
    activites = models.JSONField(default=list, help_text="codes du questionnaire")
    regime = models.CharField(max_length=20, choices=REGIMES)
    tva = models.CharField(max_length=20, choices=TVA_MODES, default="franchise")
    exercice_debut = models.DateField(null=True, blank=True)

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


class KbisFile(models.Model):
    """Piece justificative << KBIS >> (extrait RNE depuis 2023)."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="kbis")
    file = models.FileField(upload_to="kbis/")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(
        max_length=20, choices=[("inpi", "INPI"), ("user", "utilisateur")],
        default="user",
    )
