"""Journal des actions d'administration. N'écrit jamais de secret."""
import logging

from .models import SystemLog

logger = logging.getLogger(__name__)


def client_ip(request):
    """IP réelle du visiteur (Vercel : X-Forwarded-For, sinon REMOTE_ADDR)."""
    for key in (
        "HTTP_X_FORWARDED_FOR",
        "HTTP_X_REAL_IP",
        "HTTP_X_VERCEL_FORWARDED_FOR",
    ):
        raw = (request.META.get(key) or "").split(",")[0].strip()
        if raw and len(raw) <= 45:
            return raw
    ip = (request.META.get("REMOTE_ADDR") or "").strip()
    if ip and len(ip) <= 45:
        return ip
    return None


def journaliser(request, message, level="INFO", user=None, source="app"):
    """Enregistre une ligne de journal. Une panne du journal ne bloque pas l'action."""
    try:
        actor = user
        if actor is None and getattr(request, "user", None) is not None and request.user.is_authenticated:
            actor = request.user
        SystemLog.objects.create(
            level=level,
            source=source,
            message=(message or "")[:2000],
            user=actor,
            ip_address=client_ip(request),
        )
    except Exception:
        logger.exception("Journal d'administration indisponible")
