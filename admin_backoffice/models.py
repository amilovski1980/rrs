from django.db.models import Model
from django.db import models

class SiteConfiguration(models.Model):
    """
    Stocke la configuration globale du site pour permettre une gestion
    via le dashboard sans modifier les fichiers .env.
    """
    # --- SMTP / Email ---
    smtp_host = models.CharField(max_length=255, default="smtp.gmail.com", verbose_name="Hôte SMTP")
    smtp_port = models.IntegerField(default=587, verbose_name="Port SMTP")
    smtp_user = models.CharField(max_length=255, default="", verbose_name="Utilisateur SMTP")
    smtp_password = models.CharField(max_length=255, default="", verbose_name="Mot de passe SMTP")
    email_from = models.EmailField(default="no-reply@roadrunner-solutions.fr", verbose_name="Email d'expédition")

    # --- Clés API ---
    stripe_secret_key = models.CharField(max_length=255, default="", verbose_name="Clé Secrète Stripe")
    stripe_publishable_key = models.CharField(
        max_length=255, blank=True, default="", verbose_name="Clé publique Stripe",
    )
    stripe_webhook_secret = models.CharField(
        max_length=255, blank=True, default="", verbose_name="Secret webhook Stripe",
    )
    llm_api_key = models.CharField(max_length=255, default="", verbose_name="Clé API LLM")
    llm_base_url = models.CharField(
        max_length=255, blank=True, default="", verbose_name="URL de base Qwen",
        help_text="Vide = variable LLM_BASE_URL.",
    )
    llm_model = models.CharField(
        max_length=120, blank=True, default="", verbose_name="Modèle Qwen",
        help_text="Vide = variable LLM_MODEL.",
    )
    xai_api_key = models.CharField(max_length=512, blank=True, default="", verbose_name="Clé API xAI")
    xai_text_model = models.CharField(
        max_length=120, blank=True, default="", verbose_name="Modèle de chat xAI",
        help_text="Vide = variable XAI_TEXT_MODEL (grok-3 par défaut).",
    )
    xai_voice_model = models.CharField(
        max_length=120, blank=True, default="", verbose_name="Modèle vocal xAI",
        help_text="Vide = variable XAI_VOICE_MODEL.",
    )
    xai_voice = models.CharField(
        max_length=40, blank=True, default="", verbose_name="Voix xAI",
        help_text="Vide = variable XAI_VOICE.",
    )
    ai_text_provider = models.CharField(
        max_length=12,
        choices=[("qwen", "Qwen (auto-hébergé)"), ("xai", "xAI / Grok")],
        default="qwen",
        verbose_name="Fournisseur du chat Aminia",
    )
    insee_api_key = models.CharField(max_length=255, default="", verbose_name="Clé API INSEE")

    # --- Paramètres Site ---
    site_name = models.CharField(max_length=255, default="Road Runner Solutions", verbose_name="Nom du Site")
    maintenance_mode = models.BooleanField(default=False, verbose_name="Mode Maintenance")
    ai_system_prompt = models.TextField(
        blank=True,
        default="",
        verbose_name="Consigne générale de l'agent",
        help_text="Appliquée à tous les forfaits. Vide = texte par défaut.",
    )

    class Meta:
        verbose_name = "Configuration du Site"
        verbose_name_plural = "Configuration du Site"

    def __str__(self):
        return f"Configuration globale - {self.site_name}"

class SystemLog(models.Model):
    """
    Enregistre les événements système, erreurs et actions administratives.
    """
    LEVELS = [
        ('INFO', 'Information'),
        ('WARNING', 'Avertissement'),
        ('ERROR', 'Erreur'),
        ('CRITICAL', 'Critique'),
    ]
    
    timestamp = models.DateTimeField(auto_now_add=True)
    level = models.CharField(max_length=10, choices=LEVELS, default='INFO')
    message = models.TextField()
    user = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = "Log Système"
        verbose_name_plural = "Logs Système"

    def __str__(self):
        return f"[{self.timestamp}] {self.level}: {self.message[:50]}"


class SmsProviderConfig(models.Model):
    """Identifiants d'un fournisseur SMS. Les secrets ne sont jamais renvoyés en clair."""

    PROVIDERS = [
        ("ovh", "OVH"),
        ("brevo", "Brevo"),
        ("twilio", "Twilio"),
    ]
    code = models.CharField(max_length=20, unique=True, choices=PROVIDERS)
    enabled = models.BooleanField(default=False, verbose_name="Activé")
    sender_name = models.CharField(
        max_length=32, blank=True, default="", verbose_name="Nom d'expéditeur",
    )
    credentials = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Fournisseur SMS"
        verbose_name_plural = "Fournisseurs SMS"

    def __str__(self):
        return dict(self.PROVIDERS).get(self.code, self.code)


class SmsSettings(models.Model):
    """Réglage unique : quel fournisseur pilote l'envoi."""

    active_provider = models.CharField(max_length=20, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Réglage SMS"
        verbose_name_plural = "Réglages SMS"

    def __str__(self):
        return self.active_provider or "Aucun fournisseur actif"


class SmsTemplate(models.Model):
    code = models.SlugField(max_length=40, unique=True, verbose_name="Code")
    name = models.CharField(max_length=80, verbose_name="Nom")
    body = models.TextField(
        verbose_name="Message",
        help_text="Variables possibles : {prenom}, {code}, {lien}.",
    )
    is_active = models.BooleanField(default=True, verbose_name="Actif")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Modèle SMS"
        verbose_name_plural = "Modèles SMS"

    def __str__(self):
        return self.name


class SmsMessage(models.Model):
    """Journal d'envoi. Le hook dispatch_sms écrit ici, fournisseur branché ou non."""

    STATUSES = [
        ("queued", "En file"),
        ("sent", "Envoyé"),
        ("failed", "Échec"),
        ("skipped", "Non envoyé"),
    ]
    recipient = models.CharField(max_length=32, verbose_name="Destinataire")
    body = models.TextField(verbose_name="Message")
    provider = models.CharField(max_length=20, blank=True, default="")
    template = models.ForeignKey(
        SmsTemplate, null=True, blank=True, on_delete=models.SET_NULL, related_name="messages",
    )
    status = models.CharField(max_length=16, choices=STATUSES, default="skipped")
    detail = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="sms_messages",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Journal SMS"
        verbose_name_plural = "Journal SMS"

    def __str__(self):
        return f"{self.recipient} ({self.status})"
