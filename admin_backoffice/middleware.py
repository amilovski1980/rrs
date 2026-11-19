import logging
import time

from django.db.utils import OperationalError, ProgrammingError
from django.http import HttpResponse, HttpResponseForbidden

from .audit import client_ip
from .models import BannedIP, SiteConfiguration, SystemLog, VisitorHit

logger = logging.getLogger(__name__)

_SCHEMA_ERRORS = (OperationalError, ProgrammingError)

# Cache court des IP bannies (évite une requête à chaque hit).
_banned_cache = {"at": 0.0, "ips": set()}
_BANNED_TTL = 30.0


def _banned_ips():
    now = time.monotonic()
    if now - _banned_cache["at"] > _BANNED_TTL:
        try:
            _banned_cache["ips"] = set(
                BannedIP.objects.filter(active=True).values_list("ip", flat=True)
            )
            _banned_cache["at"] = now
        except Exception:
            return set()
    return _banned_cache["ips"]


class IPBanMiddleware:
    """Bloque les adresses IP bannies (le personnel garde l'accès)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ip = client_ip(request)
        if ip:
            user = getattr(request, "user", None)
            if not (user and getattr(user, "is_staff", False)):
                if ip in _banned_ips():
                    return HttpResponseForbidden(
                        "<!DOCTYPE html><html lang=\"fr\"><head><meta charset=\"utf-8\">"
                        "<title>Accès refusé</title></head><body>"
                        "<h1>Accès refusé</h1><p>Cette adresse IP a été bloquée.</p>"
                        "</body></html>",
                        content_type="text/html; charset=utf-8",
                    )
        return self.get_response(request)


class AnalyticsMiddleware:
    """Enregistre le trafic (IP, ville, page, statut) et les erreurs serveur."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            path = request.path or "/"
            if (
                not path.startswith("/static/")
                and not path.startswith("/media/")
                and path not in ("/favicon.ico", "/sw.js", "/_vercel/ping")
            ):
                ua = (request.META.get("HTTP_USER_AGENT") or "")[:255]
                VisitorHit.objects.create(
                    ip=client_ip(request) or "0.0.0.0",
                    path=path[:255],
                    method=(request.method or "GET")[:8],
                    status=getattr(response, "status_code", 200),
                    city=(request.META.get("HTTP_X_VERCEL_IP_CITY") or "")[:80],
                    country=(request.META.get("HTTP_X_VERCEL_IP_COUNTRY") or "")[:8],
                    user_agent=ua,
                )
            if getattr(response, "status_code", 200) >= 500:
                SystemLog.objects.create(
                    level="ERROR",
                    source="server",
                    message=f"{request.method} {path} → {response.status_code}",
                    ip_address=client_ip(request),
                )
        except Exception:
            logger.exception("Analytique indisponible")
        return response


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


def _is_schema_error(exc) -> bool:
    if isinstance(exc, _SCHEMA_ERRORS):
        return True
    cause = getattr(exc, "__cause__", None)
    return isinstance(cause, _SCHEMA_ERRORS)


def _schema_fallback():
    """Page lisible quand le schéma n'a pas pu être rattrapé. Jamais un 500."""
    return HttpResponse(
        "<!DOCTYPE html><html lang=\"fr\"><head><meta charset=\"utf-8\">"
        "<title>Mise à jour</title></head><body>"
        "<h1>Mise à jour de la base</h1>"
        "<p>Les pages d'administration seront de nouveau disponibles dès que "
        "le schéma est à jour. Rechargez la page dans un instant.</p>"
        "</body></html>",
        status=200,
        content_type="text/html; charset=utf-8",
    )


class SchemaRetryMiddleware:
    """Si une page lit une colonne absente, on migre puis on réaffiche.

    Vaut pour tout le site : le sélecteur de sociétés lit Company sur chaque
    page, donc une seule colonne manquante (ex. capital) faisait tomber la
    page d'accueil, la démo et le cockpit en 500.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if not _is_schema_error(exception):
            return None
        if getattr(request, "_schema_retried", False):
            return _schema_fallback()
        request._schema_retried = True
        logger.error("Schéma incomplet (%s), rattrapage", exception)
        from core.deploy import assurer_migrations

        assurer_migrations(force=True)
        try:
            response = self.get_response(request)
        except Exception as exc:
            if _is_schema_error(exc):
                return _schema_fallback()
            return None
        if getattr(response, "status_code", 500) >= 500:
            return _schema_fallback()
        return response
