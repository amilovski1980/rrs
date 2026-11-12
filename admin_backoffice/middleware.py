import logging

from django.http import HttpResponseForbidden

from .models import SiteConfiguration

logger = logging.getLogger(__name__)


class DynamicConfigMiddleware:
    """Applique la configuration du back-office sans effacer les secrets d'environnement.

    Une valeur vide en base ne remplace pas la variable d'environnement.
    Le SMTP n'est appliqué que si un compte ou un mot de passe a été saisi,
    pour ne pas forcer l'hôte par défaut sur une installation qui n'a rien réglé.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            config, _ = SiteConfiguration.objects.get_or_create(id=1)
            from django.conf import settings

            if config.smtp_user or config.smtp_password:
                if config.smtp_host:
                    settings.EMAIL_HOST = config.smtp_host
                if config.smtp_port:
                    settings.EMAIL_PORT = config.smtp_port
                settings.EMAIL_HOST_USER = config.smtp_user
                if config.smtp_password:
                    settings.EMAIL_HOST_PASSWORD = config.smtp_password
                if config.email_from:
                    settings.DEFAULT_FROM_EMAIL = config.email_from

            if config.stripe_secret_key:
                settings.STRIPE_SECRET_KEY = config.stripe_secret_key
            if config.stripe_publishable_key:
                settings.STRIPE_PUBLISHABLE_KEY = config.stripe_publishable_key
            if config.stripe_webhook_secret:
                settings.STRIPE_WEBHOOK_SECRET = config.stripe_webhook_secret
            if config.llm_api_key:
                settings.LLM_API_KEY = config.llm_api_key
            if getattr(config, "llm_base_url", ""):
                settings.LLM_BASE_URL = config.llm_base_url
            if getattr(config, "llm_model", ""):
                settings.LLM_MODEL = config.llm_model
            if getattr(config, "xai_api_key", ""):
                settings.XAI_API_KEY = config.xai_api_key
            if getattr(config, "xai_text_model", ""):
                settings.XAI_TEXT_MODEL = config.xai_text_model
            if getattr(config, "xai_voice_model", ""):
                settings.XAI_VOICE_MODEL = config.xai_voice_model
            if getattr(config, "xai_voice", ""):
                settings.XAI_VOICE = config.xai_voice
            if getattr(config, "ai_text_provider", "") in ("qwen", "xai"):
                settings.AI_TEXT_PROVIDER = config.ai_text_provider
            if config.insee_api_key:
                settings.INSEE_API_KEY = config.insee_api_key
            if config.site_name:
                settings.SITE_NAME = config.site_name
            if config.ai_system_prompt:
                settings.AI_SYSTEM_PROMPT = config.ai_system_prompt

            path = request.path or ""
            staff = bool(getattr(request.user, "is_staff", False) and getattr(request.user, "is_active", False))
            impersonating = bool(request.session.get("admin_impersonator_id"))
            if (
                config.maintenance_mode
                and not staff
                and not impersonating
                and not path.startswith("/static/")
                and not path.startswith("/media/")
            ):
                return HttpResponseForbidden(
                    "<h1>Site en maintenance</h1><p>Nous revenons très vite.</p>"
                )
        except Exception:
            logger.exception("Configuration dynamique indisponible")

        return self.get_response(request)
