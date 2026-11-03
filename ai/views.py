"""Session vocale Grok et exécution des outils comptables, côté serveur."""
import json

import httpx
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .assistant import TOOLS, execute_tool, instructions_for, resolve_company

SESSION_KEY = "voice_company_id"


def _json_body(request):
    if not request.body:
        return {}
    try:
        data = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _auth_required(request):
    if request.user.is_authenticated:
        return None
    return JsonResponse(
        {
            "error": "auth",
            "message": "Connectez-vous au cockpit pour que je gère votre société.",
        },
        status=401,
    )


def _mint_secret():
    key = settings.XAI_API_KEY
    if not key:
        return None, "La clé XAI_API_KEY n'est pas configurée sur le serveur."
    response = httpx.post(
        "https://api.x.ai/v1/realtime/client_secrets",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        json={"expires_after": {"seconds": 600}},
        timeout=20,
    )
    if response.status_code >= 400:
        # Certaines versions de l'endpoint n'acceptent pas de corps.
        response = httpx.post(
            "https://api.x.ai/v1/realtime/client_secrets",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={},
            timeout=20,
        )
    if response.status_code >= 400:
        return None, "L'API vocale Grok a refusé la session."
    payload = response.json()
    token = payload.get("value") or payload.get("client_secret") or payload.get("secret") or payload.get("token")
    if isinstance(token, dict):
        token = token.get("value") or token.get("secret")
    if not token:
        return None, "Jeton vocal absent de la réponse xAI."
    return {"token": token, "expires_at": payload.get("expires_at")}, None


@require_POST
def voice_session(request):
    denied = _auth_required(request)
    if denied:
        return denied
    body = _json_body(request) or {}
    company = resolve_company(request.user, body.get("company_id") or request.session.get(SESSION_KEY))
    if company is not None:
        request.session[SESSION_KEY] = str(company.id)
    secret, error = _mint_secret()
    if error:
        return JsonResponse({"error": "voice", "message": error}, status=503)
    return JsonResponse({
        "token": secret["token"],
        "expires_at": secret["expires_at"],
        "url": f"wss://api.x.ai/v1/realtime?model={settings.XAI_VOICE_MODEL}",
        "voice": settings.XAI_VOICE,
        "instructions": instructions_for(request.user, company),
        "tools": TOOLS,
        "company_id": str(company.id) if company else None,
        "company_name": company.denomination if company else "",
    })


@require_POST
def voice_tool(request):
    denied = _auth_required(request)
    if denied:
        return denied
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "JSON invalide."}, status=400)
    name = body.get("name") or ""
    args = body.get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Arguments illisibles."}, status=400)

    company = resolve_company(request.user, request.session.get(SESSION_KEY))

    def remember(selected):
        nonlocal company
        company = selected
        request.session[SESSION_KEY] = str(selected.id)

    try:
        result = execute_tool(request.user, company, name, args, remember)
    except PermissionError as exc:
        return JsonResponse({"error": str(exc)}, status=403)
    except Exception:
        return JsonResponse({"error": "L'outil comptable a échoué."}, status=500)
    return JsonResponse({"output": result})
