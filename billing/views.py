import hashlib
import hmac
import json
import logging
import time

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .access import _plan_matrix, snapshot
from .catalog import BOOL_FEATURES, ensure_catalog
from .models import Plan
from .services import apply_checkout_session, record_and_apply
from .stripe_api import (
    StripeError,
    StripeNotConfigured,
    create_checkout_session,
    retrieve_checkout_session,
    stripe_secret,
    stripe_webhook_secret,
)

logger = logging.getLogger(__name__)

SIGNATURE_TOLERANCE = 300


def _plans():
    ensure_catalog()
    return list(Plan.objects.filter(is_active=True).order_by("price_eur", "name"))


def _verify_signature(payload: bytes, header: str, secret: str) -> bool:
    if not payload or not header or not secret:
        return False
    parts: dict[str, list[str]] = {}
    for item in header.split(","):
        key, _, value = item.partition("=")
        parts.setdefault(key.strip(), []).append(value.strip())
    timestamps = parts.get("t") or []
    signatures = parts.get("v1") or []
    if not timestamps or not signatures:
        return False
    try:
        stamp = int(timestamps[0])
    except ValueError:
        return False
    if abs(int(time.time()) - stamp) > SIGNATURE_TOLERANCE:
        return False
    signed = timestamps[0].encode("utf-8") + b"." + payload
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, candidate) for candidate in signatures)


@login_required
def upgrade(request):
    plans = _plans()
    state = snapshot(request.user)
    session_id = (request.GET.get("session_id") or "").strip()
    if session_id:
        try:
            session = retrieve_checkout_session(session_id)
        except StripeNotConfigured:
            messages.warning(
                request,
                "Le paiement par carte n'est pas disponible : Stripe n'est pas configuré.",
            )
        except StripeError:
            messages.warning(request, "Le paiement est en cours de confirmation.")
        else:
            owner = session.get("client_reference_id") or (session.get("metadata") or {}).get("user_id")
            if str(owner or "") == str(request.user.pk) and apply_checkout_session(session):
                messages.success(request, "Votre forfait est à jour. Les fonctions débloquées sont disponibles.")
                state = snapshot(request.user)
            elif str(owner or "") != str(request.user.pk):
                messages.warning(request, "Cette confirmation de paiement ne correspond pas à votre compte.")
    if request.GET.get("paiement") == "annule":
        messages.info(request, "Paiement annulé. Votre forfait n'a pas changé.")
    configured = bool(stripe_secret())
    from companies.models import INVOICE_THEMES

    labels = dict(INVOICE_THEMES)
    cards = []
    for plan in plans:
        matrix = _plan_matrix(plan)
        cards.append({
            "plan": plan,
            "matrix": matrix,
            "themes": ", ".join(labels.get(code, code) for code in matrix.get("themes") or []),
            "current": state["code"] == plan.code and state["status"] in ("active", "trialing", "past_due"),
        })
    return render(request, "billing/upgrade.html", {
        "plans": plans,
        "cards": cards,
        "features": BOOL_FEATURES,
        "state": state,
        "stripe_ready": configured,
    })


@login_required
@require_POST
def checkout(request):
    code = (request.POST.get("plan") or "").strip()
    plan = get_object_or_404(Plan, code=code, is_active=True)
    state = snapshot(request.user)
    if state["code"] == plan.code and state["status"] in ("active", "trialing"):
        messages.info(request, "Ce forfait est déjà le vôtre.")
        return redirect("plan_upgrade")
    if not stripe_secret():
        messages.error(
            request,
            "Le paiement par carte n'est pas disponible pour le moment. "
            "Stripe n'est pas configuré.",
        )
        return redirect("plan_upgrade")
    success = request.build_absolute_uri(reverse("plan_upgrade"))
    success = success + ("&" if "?" in success else "?") + "paiement=ok&session_id={CHECKOUT_SESSION_ID}"
    cancel = request.build_absolute_uri(reverse("plan_upgrade") + "?paiement=annule")
    try:
        session = create_checkout_session(
            user=request.user,
            plan=plan,
            success_url=success,
            cancel_url=cancel,
        )
    except StripeNotConfigured:
        messages.error(
            request,
            "Le paiement par carte n'est pas disponible pour le moment. "
            "Stripe n'est pas configuré.",
        )
        return redirect("plan_upgrade")
    except StripeError:
        messages.error(request, "Le paiement par carte n'a pas pu être ouvert. Réessayez dans un instant.")
        return redirect("plan_upgrade")
    return redirect(session["url"])


@csrf_exempt
@require_POST
def stripe_webhook(request):
    secret = stripe_webhook_secret()
    if not secret:
        return HttpResponse("Webhook Stripe non configuré.", status=400)
    header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    if not _verify_signature(request.body, header, secret):
        return HttpResponse("Signature invalide.", status=400)
    try:
        event = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return HttpResponse("JSON invalide.", status=400)
    if not isinstance(event, dict) or not event.get("id"):
        return HttpResponse("Événement incomplet.", status=400)
    try:
        record_and_apply(event)
    except Exception:
        logger.exception("Webhook Stripe %s", event.get("type") or "")
        return HttpResponse("Traitement impossible.", status=500)
    return HttpResponse(status=200)
