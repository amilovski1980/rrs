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
    llm_api_key = models.CharField(
        max_length=255, default="", verbose_name="Clé API LLM (Qwen / Ollama)"
    )
    llm_base_url = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="URL de base LLM (Qwen / Ollama)",
        help_text="Vide = variable LLM_BASE_URL. Ollama : http://localhost:11434/v1",
    )
    llm_model = models.CharField(
        max_length=120,
        blank=True,
        default="",
        verbose_name="Modèle LLM (Qwen / Ollama)",
        help_text="Vide = variable LLM_MODEL. Utilisez « Lister les modèles » pour choisir.",
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
    voice_provider = models.CharField(
        max_length=14,
        choices=[
            ("xai", "xAI Realtime (live)"),
            ("elevenlabs", "ElevenLabs (synthèse texte → voix)"),
        ],
        default="elevenlabs",
        blank=True,
        verbose_name="Fournisseur de la voix",
    )
    voice_call_provider = models.CharField(
        max_length=14,
        choices=[
            ("xai", "xAI / Grok (temps réel)"),
            ("elevenlabs", "ElevenLabs (agent temps réel)"),
        ],
        default="xai",
        blank=True,
        verbose_name="Session vocale en direct",
        help_text="Le fournisseur qui porte l'appel Aminia (micro, tour de parole, outils).",
    )
    elevenlabs_agent_id = models.CharField(
        max_length=80, blank=True, default="", verbose_name="Agent ElevenLabs (ID)",
        help_text="Créé via « Créer / mettre à jour l'agent ElevenLabs ».",
    )
    voice_gender = models.CharField(
        max_length=8,
        choices=[("femme", "Voix de femme"), ("homme", "Voix d'homme")],
        default="femme",
        blank=True,
        verbose_name="Genre de la voix",
    )
    elevenlabs_api_key = models.CharField(
        max_length=512, blank=True, default="", verbose_name="Clé API ElevenLabs",
    )
    elevenlabs_model = models.CharField(
        max_length=80, blank=True, default="", verbose_name="Modèle ElevenLabs",
        help_text="Vide = eleven_flash_v2_5 (multilingue rapide).",
    )
    elevenlabs_voice_female = models.CharField(
        max_length=80, blank=True, default="21m00Tcm4TlvDq8tWv",
        verbose_name="Voix ElevenLabs — femme",
    )
    elevenlabs_voice_male = models.CharField(
        max_length=80, blank=True, default="onwK4e9ZLuTAKqWW03F9",
        verbose_name="Voix ElevenLabs — homme",
    )
    ai_text_provider = models.CharField(
        max_length=12,
        choices=[
            ("qwen", "Qwen (vLLM / compatible OpenAI)"),
            ("ollama", "Ollama (local)"),
            ("xai", "xAI / Grok"),
        ],
        default="qwen",
        verbose_name="Fournisseur du chat Aminia",
    )
    insee_api_key = models.CharField(max_length=255, default="", verbose_name="Clé API INSEE")

    # --- Facturation électronique (Factur-X / plateforme agréée) ---
    einvoicing_enabled = models.BooleanField(
        default=False, verbose_name="Activer la facturation électronique"
    )
    einvoicing_provider = models.CharField(
        max_length=20,
        choices=[
            ("generic", "Plateforme agréée / API générique"),
            ("chorus", "Chorus Pro"),
            ("ppf", "Portail public de facturation"),
            ("manual", "Dépôt manuel (XML/PDF)"),
        ],
        default="generic",
        blank=True,
        verbose_name="Plateforme de dépôt",
    )
    einvoicing_api_url = models.URLField(
        blank=True,
        default="",
        verbose_name="URL de l'API de dépôt",
        help_text="Endpoint qui reçoit le fichier Factur-X (multipart/form-data).",
    )
    einvoicing_api_key = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Clé API de la plateforme",
    )
    einvoicing_sender_siret = models.CharField(
        max_length=14,
        blank=True,
        default="",
        verbose_name="SIRET émetteur",
        help_text="SIRET à 14 chiffres utilisé comme identifiant d'émission.",
    )
    einvoicing_default_profile = models.CharField(
        max_length=12,
        choices=[
            ("BASIC", "Factur-X BASIC"),
            ("EN16931", "Factur-X EN 16931"),
            ("EXTENDED", "Factur-X EXTENDED"),
        ],
        default="EN16931",
        verbose_name="Profil Factur-X par défaut",
    )

    # --- Paramètres Site ---
    site_name = models.CharField(max_length=255, default="Road Runner Solutions", verbose_name="Nom du Site")
    maintenance_mode = models.BooleanField(default=False, verbose_name="Mode Maintenance")
    ai_system_prompt = models.TextField(
        blank=True,
        default="",
        verbose_name="Consigne générale de l'agent",
        help_text="Appliquée à tous les forfaits. Vide = texte par défaut.",
    )
    admin_ai_prompt = models.TextField(
        blank=True,
        default="",
        verbose_name="Consigne de l'agent administrateur",
        help_text=(
            "Réservée au personnel : corrections du site, configuration et "
            "assistant admin développeur. Vide = texte par défaut."
        ),
    )

    # --- SEO & Google Search Console (agent SEO du back-office) ---
    seo_gsc_site = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Propriété Search Console",
        help_text="Ex. sc-domain:rrsolutions.io ou https://rrsolutions.io/",
    )
    seo_service_email = models.EmailField(
        blank=True,
        default="",
        verbose_name="E-mail du compte de service Google",
    )
    seo_private_key = models.TextField(
        blank=True,
        default="",
        verbose_name="Clé privée du compte de service (PEM)",
        help_text="Collez la clé 'private_key' du fichier JSON du compte de service Google.",
    )
    seo_title = models.CharField(
        max_length=120,
        blank=True,
        default="",
        verbose_name="Titre SEO de la vitrine",
    )
    seo_description = models.CharField(
        max_length=320,
        blank=True,
        default="",
        verbose_name="Description SEO de la vitrine",
    )

    # --- Apparence du site public (éditeur du back-office) ---
    site_accent = models.CharField(
        max_length=7,
        blank=True,
        default="",
        verbose_name="Couleur d'accent du site (HEX)",
        help_text="Ex. #ff7a45. Vide = palette par défaut du thème sombre.",
    )
    home_title = models.CharField(
        max_length=160,
        blank=True,
        default="",
        verbose_name="Titre de la page d'accueil",
        help_text="Remplace le grand titre de la vitrine. Vide = texte par défaut.",
    )
    home_subtitle = models.CharField(
        max_length=260,
        blank=True,
        default="",
        verbose_name="Sous-titre de la page d'accueil",
    )
    logo_dark = models.BinaryField(null=True, blank=True, verbose_name="Logo version sombre")
    logo_dark_type = models.CharField(max_length=40, blank=True, default="")
    logo_light = models.BinaryField(null=True, blank=True, verbose_name="Logo version claire")
    logo_light_type = models.CharField(max_length=40, blank=True, default="")

    # --- Coordonnées de contact (emails automatiques, mentions légales) ---
    contact_address = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Adresse postale",
        help_text="Visible dans les emails automatiques et les mentions légales si renseignée.",
    )
    contact_phone = models.CharField(
        max_length=40,
        blank=True,
        default="",
        verbose_name="Téléphone",
    )
    contact_email = models.EmailField(
        blank=True,
        default="",
        verbose_name="Email de contact",
        help_text="Vide = email d'expédition configuré ci-dessus.",
    )

    class Meta:
        verbose_name = "Configuration du Site"
        verbose_name_plural = "Configuration du Site"

    def __str__(self):
        return f"Configuration globale - {self.site_name}"


class EmailTemplate(models.Model):
    """Texte personnalisable d'un email automatique.

    Aucune ligne n'est créée tant que le personnel n'enregistre pas de
    personnalisation : l'application retombe alors sur les textes par défaut
    documentés dans ``admin_backoffice.email_templates``.
    """

    code = models.SlugField(max_length=40, unique=True, verbose_name="Code")
    subject = models.CharField(max_length=255, verbose_name="Objet")
    body = models.TextField(verbose_name="Corps")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Mis à jour le")
    updated_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="email_templates_updated",
        verbose_name="Mis à jour par",
    )

    class Meta:
        ordering = ["code"]
        verbose_name = "Modèle d'email"
        verbose_name_plural = "Modèles d'email"

    def __str__(self):
        return self.code


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
    SOURCES = [
        ('app', 'Application'),
        ('agent', 'Agent Aminia'),
        ('server', 'Serveur'),
    ]

    timestamp = models.DateTimeField(auto_now_add=True)
    level = models.CharField(max_length=10, choices=LEVELS, default='INFO')
    source = models.CharField(max_length=10, choices=SOURCES, default='app')
    message = models.TextField()
    user = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = "Log Système"
        verbose_name_plural = "Logs Système"

    def __str__(self):
        return f"[{self.timestamp}] {self.level}: {self.message[:50]}"


class VisitorHit(models.Model):
    """Trafic public : IP, ville (en-têtes Vercel), page et statut HTTP."""

    ip = models.CharField(max_length=45, db_index=True)
    path = models.CharField(max_length=255)
    method = models.CharField(max_length=8, default="GET")
    status = models.PositiveSmallIntegerField(default=200)
    city = models.CharField(max_length=80, blank=True, default="")
    country = models.CharField(max_length=8, blank=True, default="")
    user_agent = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Visite"
        verbose_name_plural = "Visites"

    def __str__(self):
        return f"{self.created_at:%d/%m %H:%M} {self.ip} {self.path}"


class BannedIP(models.Model):
    """Adresse IP bloquée côté site public (le personnel reste autorisé)."""

    ip = models.CharField(max_length=45, unique=True)
    reason = models.CharField(max_length=200, blank=True, default="")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "IP bannie"
        verbose_name_plural = "IP bannies"

    def __str__(self):
        return self.ip


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
