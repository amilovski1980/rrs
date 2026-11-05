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


# ---------------------------------------------------------------------------
# Validation humaine des brouillons IA (clients, etc.)
# ---------------------------------------------------------------------------
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.context import resolve_company as resolve_web_company

from .models import AiDraftEntry


@login_required
def draft_list(request):
    company = resolve_web_company(request)
    if company is None:
        return redirect("onboarding")
    drafts = AiDraftEntry.objects.filter(company=company).order_by("-created_at")
    return render(request, "ai/draft_list.html", {
        "company": company,
        "drafts": drafts,
    })


@login_required
def draft_detail(request, pk):
    company = resolve_web_company(request)
    if company is None:
        return redirect("onboarding")
    draft = get_object_or_404(AiDraftEntry, pk=pk, company=company)
    return render(request, "ai/draft_detail.html", {
        "company": company,
        "draft": draft,
    })


@login_required
@require_POST
def draft_approve(request, pk):
    company = resolve_web_company(request)
    if company is None:
        return redirect("onboarding")
    draft = get_object_or_404(AiDraftEntry, pk=pk, company=company)
    if draft.status != "pending":
        messages.error(request, "Ce brouillon a déjà été traité.")
        return redirect("ai_draft_detail", pk=draft.id)

    if draft.kind == "client":
        from documents.models import Client

        data = draft.proposed_data or {}
        name = (data.get("name") or "").strip()
        if len(name) < 2:
            messages.error(request, "Le brouillon client est incomplet (nom manquant).")
            return redirect("ai_draft_detail", pk=draft.id)
        siren = "".join(c for c in str(data.get("siren") or "") if c.isdigit())
        client = Client.objects.create(
            company=company,
            name=name[:200],
            siren=siren if len(siren) == 9 else "",
            address=(data.get("address") or "")[:255],
            email=(data.get("email") or "")[:200],
            phone=(data.get("phone") or "")[:30],
            notes=(data.get("notes") or "")[:2000],
        )
        draft.created_client = client
        draft.status = "validated"
        draft.validated_at = timezone.now()
        draft.save(update_fields=["created_client", "status", "validated_at"])
        messages.success(request, f"Client « {client.name} » créé après validation.")
        return redirect("client_detail", pk=client.id)

    messages.error(request, "Ce type de brouillon ne peut pas être validé ici.")
    return redirect("ai_draft_detail", pk=draft.id)


@login_required
@require_POST
def draft_reject(request, pk):
    company = resolve_web_company(request)
    if company is None:
        return redirect("onboarding")
    draft = get_object_or_404(AiDraftEntry, pk=pk, company=company)
    if draft.status != "pending":
        messages.error(request, "Ce brouillon a déjà été traité.")
        return redirect("ai_draft_detail", pk=draft.id)
    draft.status = "rejected"
    draft.validated_at = timezone.now()
    draft.save(update_fields=["status", "validated_at"])
    messages.success(request, "Brouillon rejeté.")
    return redirect("ai_drafts")




# ---------------------------------------------------------------------------
# Chat texte Aminia
# ---------------------------------------------------------------------------
from core.context import resolve_company as resolve_web_company_chat

from .chat import get_or_create_conversation, run_chat_turn
from .models import Conversation


@login_required
def chat_page(request):
    """Page chat dédiée (fallback hors panneau) — company-scoped."""
    company = resolve_web_company_chat(request)
    if company is None:
        return redirect("onboarding")
    conversation = get_or_create_conversation(request.user, company)
    messages_qs = conversation.messages.order_by("created_at")
    return render(request, "ai/chat.html", {
        "company": company,
        "conversation": conversation,
        "chat_messages": messages_qs,
    })


@login_required
@require_POST
def chat_message(request):
    """JSON : envoi d'un message chat (CSRF + login + tenant)."""
    company = resolve_web_company_chat(request)
    if company is None:
        return JsonResponse(
            {"ok": False, "error": "Aucune société sélectionnée."},
            status=400,
        )
    body = _json_body(request)
    if body is None:
        text = (request.POST.get("message") or "").strip()
        conversation_id = request.POST.get("conversation_id") or ""
    else:
        text = (body.get("message") or "").strip()
        conversation_id = body.get("conversation_id") or ""

    conversation = None
    if conversation_id:
        conversation = Conversation.objects.filter(
            pk=conversation_id, user=request.user, company=company
        ).first()
        if conversation is None:
            return JsonResponse({"ok": False, "error": "Conversation introuvable."}, status=404)
    else:
        conversation = get_or_create_conversation(request.user, company)

    result = run_chat_turn(request.user, company, conversation, text)
    status = result.pop("status", 200)
    if not result.get("ok") and status == 200:
        status = 400
    return JsonResponse(result, status=status)
