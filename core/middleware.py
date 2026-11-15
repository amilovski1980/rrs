"""Mode démo : lecture seule, aucune écriture en base.

Le compte de démonstration est partagé et pré-rempli. Toute requête qui
modifie des données (POST/PUT/PATCH/DELETE) est interceptée avant la vue.
Seules la connexion et la déconnexion restent autorisées.
"""

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
ALLOWED_PATHS = {
    "/compte/",
    "/compte/demo/",
    "/compte/logout/",
    # Aperçu facture / devis : lecture pure, aucune écriture en base.
    "/factures/apercu/",
    "/devis/apercu/",
}


def _allowed(request) -> bool:
    path = request.path or ""
    for allowed in ALLOWED_PATHS:
        if path == allowed or path == "/dark" + allowed:
            return True
    return False
DEMO_READ_ONLY_MESSAGE = (
    "Mode démo en lecture seule : aucune modification n'est enregistrée."
)


class DemoModeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        session = getattr(request, "session", None)
        if (
            session is not None
            and session.get("demo_mode")
            and request.method not in SAFE_METHODS
            and not _allowed(request)
        ):
            wants_json = (
                "application/json" in (request.headers.get("Accept") or "")
                or request.headers.get("X-Requested-With") == "XMLHttpRequest"
            )
            if wants_json:
                return JsonResponse(
                    {"error": "demo_read_only", "message": DEMO_READ_ONLY_MESSAGE},
                    status=403,
                )
            messages.info(request, DEMO_READ_ONLY_MESSAGE)
            return redirect(reverse("cockpit"))
        return self.get_response(request)
