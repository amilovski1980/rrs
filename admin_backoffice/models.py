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
    llm_api_key = models.CharField(max_length=255, default="", verbose_name="Clé API LLM")
    insee_api_key = models.CharField(max_length=255, default="", verbose_name="Clé API INSEE")

    # --- Paramètres Site ---
    site_name = models.CharField(max_length=255, default="Road Runner Solutions", verbose_name="Nom du Site")
    maintenance_mode = models.BooleanField(default=False, verbose_name="Mode Maintenance")

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
