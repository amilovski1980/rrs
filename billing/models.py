import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


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
    entitlements = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Matrice de fonctions",
        help_text="Matrice éditable : fonctions et modèles de facture.",
    )
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
        ("unpaid", "Impayé"),
        ("canceled", "Résilié"),
    ]
    FOLLOW_UP = [
        ("", "Aucun"),
        ("to_follow", "À relancer"),
        ("reminded", "Relancé"),
        ("resolved", "Régularisé"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscriptions"
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT)
    stripe_subscription_id = models.CharField(max_length=50, unique=True, null=True, blank=True)
    stripe_customer_id = models.CharField(max_length=50, blank=True, default="")
    status = models.CharField(max_length=12, choices=STATUSES, default="trialing")
    follow_up = models.CharField(
        max_length=20, choices=FOLLOW_UP, blank=True, default="", verbose_name="Suivi",
    )
    staff_note = models.TextField(blank=True, default="", verbose_name="Note interne")
    current_period_end = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_active(self):
        return self.status in ("trialing", "active")

    @property
    def needs_payment_attention(self):
        return self.status in ("past_due", "unpaid") or self.follow_up == "to_follow"


class SubscriptionInvoice(models.Model):
    """Reçu d'abonnement visible du back-office.

    Ce n'est pas une facture client (devis, avoir, PDF du cockpit). Le modèle
    garde une trace locale des encaissements Stripe pour que l'équipe puisse
    suivre un client même sans rouvrir Stripe.
    """

    STATUSES = [
        ("paid", "Payée"),
        ("open", "À payer"),
        ("failed", "Échec"),
        ("void", "Annulée"),
        ("uncollectible", "Irrécouvrable"),
        ("draft", "Brouillon"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscription_invoices",
    )
    subscription = models.ForeignKey(
        Subscription, null=True, blank=True, on_delete=models.SET_NULL, related_name="invoices",
    )
    external_id = models.CharField(max_length=80, unique=True)
    number = models.CharField(max_length=40, blank=True, default="")
    amount_eur = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUSES, default="open")
    description = models.CharField(max_length=255, blank=True, default="")
    failure_message = models.CharField(max_length=400, blank=True, default="")
    hosted_url = models.CharField(max_length=500, blank=True, default="")
    staff_note = models.TextField(blank=True, default="")
    issued_at = models.DateTimeField(default=timezone.now)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-issued_at", "-created_at"]

    def __str__(self):
        label = self.number or self.external_id
        return f"{label} — {self.amount_eur} €"


class StripeEvent(models.Model):
    """Journal brut des webhooks Stripe (idempotence)."""

    external_id = models.CharField(max_length=60, unique=True)
    type = models.CharField(max_length=40)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)
