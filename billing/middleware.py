"""Refuse l'usage d'une fonction hors forfait sans erreur 500.

Les entrées restent visibles dans l'interface. Ici, l'appel direct est
renvoyé vers la page forfait, ou en JSON pour la voix et le chat.
"""
from __future__ import annotations

import logging

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect

logger = logging.getLogger(__name__)

# Préfixes les plus longs d'abord.
RULES = (
    ("/factures/devis/", "quotes"),
    ("/factures/clients/", "clients"),
    ("/factures/produits/", "products"),
    ("/factures/projets/", "projects"),
    ("/factures/avoirs/", "credit_notes"),
    ("/factures/paiements/", "payments"),
    ("/factures/tickets/", "tickets"),
    ("/factures/import-pdf/", "invoice_import"),
    ("/factures/", "invoices"),
    ("/agent/session/", "ai_voice"),
    ("/agent/outil/", "ai_voice"),
    ("/agent/chat/", "ai_chat"),
    ("/agent/brouillons/", "ai_drafts"),
    ("/compta/ecriture/", "entries"),
    ("/compta/grand-livre/", "ledger"),
    ("/compta/balance/", "balance"),
)

JSON_PREFIXES = ("/agent/session/", "/agent/outil/", "/agent/chat/message/")


def _feature_for(path: str) -> str | None:
    for prefix, feature in RULES:
        if path.startswith(prefix):
            return feature
    return None


class PlanGateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            blocked = self._blocked(request)
        except Exception:
            logger.exception("Contrôle de forfait indisponible")
            blocked = None
        if blocked is not None:
            return blocked
        return self.get_response(request)

    def _blocked(self, request):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return None
        feature = _feature_for(request.path or "")
        if not feature:
            return None
        from billing.access import UPGRADE_MESSAGE, feature_on

        if feature_on(user, feature):
            return None
        if request.path.startswith(JSON_PREFIXES):
            return JsonResponse(
                {
                    "ok": False,
                    "error": UPGRADE_MESSAGE,
                    "message": UPGRADE_MESSAGE,
                    "upgrade": True,
                },
                status=403,
            )
        try:
            messages.info(request, UPGRADE_MESSAGE)
        except Exception:
            logger.exception("Message de forfait non enregistré")
        return redirect("plan_upgrade")
