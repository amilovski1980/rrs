"""Journal des actions d'administration. N'écrit jamais de secret."""
import logging

from .models import SystemLog

logger = logging.getLogger(__name__)


def _ip(request):
    ip = (request.META.get("REMOTE_ADDR") or "").strip()
    if ip and len(ip) <= 45:
        return ip
    return None


def journaliser(request, message, level="INFO", user=None):
    """Enregistre une ligne de journal. Une panne du journal ne bloque pas l'action."""
    try:
        actor = user
        if actor is None and getattr(request, "user", None) is not None and request.user.is_authenticated:
            actor = request.user
        SystemLog.objects.create(
            level=level,
            message=(message or "")[:2000],
            user=actor,
            ip_address=_ip(request),
        )
    except Exception:
        logger.exception("Journal d'administration indisponible")
