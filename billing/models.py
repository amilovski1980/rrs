import uuid

from django.conf import settings
from django.db import models


class Plan(models.Model):
    """Forfait commercial. Le code (micro, reel, pro, starter, illimite…)
    sert aussi à choisir la consigne de l'agent et les outils autorisés."""

    code = models.CharField(max_length=20, unique=True)  # micro / reel / pro
    name = models.CharField(max_length=50)
    price_eur = models.DecimalField(max_digits=6, decimal_places=2)
    trial_days = models.PositiveIntegerField(default=14)
    description = models.TextField(blank=True, default="")
    max_companies = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="Sociétés maximum",
        help_text="Vide = illimité.",
    )
    max_invoices_month = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="Factures par mois",
        help_text="Vide = illimité.",
    )
    max_ai_requests_month = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="Requêtes IA par mois",
        help_text="Vide = illimité.",
    )
    features = models.JSONField(default=list, blank=True, verbose_name="Fonctions incluses")
    is_active = models.BooleanField(default=True, verbose_name="Proposé aux clients")
    ai_prompt = models.TextField(
        blank=True,
        default="",
        verbose_name="Consigne de l'agent",
        help_text="Vide = consigne par défaut selon le code du forfait.",
    )

    class Meta:
        ordering = ["price_eur", "name"]

    def __str__(self):
        return self.name


class Subscription(models.Model):
    STATUSES = [
        ("trialing", "Essai"),
        ("active", "Actif"),
        ("past_due", "Retard de paiement"),
        ("canceled", "Résilié"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscriptions"
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT)
    stripe_subscription_id = models.CharField(max_length=50, unique=True, null=True, blank=True)
    status = models.CharField(max_length=12, choices=STATUSES, default="trialing")
    current_period_end = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_active(self):
        return self.status in ("trialing", "active")


class StripeEvent(models.Model):
    """Journal brut des webhooks Stripe (idempotence)."""

    external_id = models.CharField(max_length=60, unique=True)
    type = models.CharField(max_length=40)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)
