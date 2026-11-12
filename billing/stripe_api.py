"""Client Stripe minimal (Checkout, solde, annulation). Les secrets ne sont jamais journalisés."""
from __future__ import annotations

import logging

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

API = "https://api.stripe.com"


class StripeNotConfigured(Exception):
    pass


class StripeError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.message = message
        self.status = status


def _config():
    from admin_backoffice.models import SiteConfiguration

    return SiteConfiguration.objects.filter(pk=1).first()


def _overlay(env_value: str, db_value: str) -> str:
    db_value = (db_value or "").strip()
    if db_value:
        return db_value
    return (env_value or "").strip()


def stripe_secret() -> str:
    config = _config()
    return _overlay(
        getattr(settings, "STRIPE_SECRET_KEY", ""),
        getattr(config, "stripe_secret_key", "") if config else "",
    )


def stripe_publishable() -> str:
    config = _config()
    return _overlay(
        getattr(settings, "STRIPE_PUBLISHABLE_KEY", ""),
        getattr(config, "stripe_publishable_key", "") if config else "",
    )


def stripe_webhook_secret() -> str:
    config = _config()
    return _overlay(
        getattr(settings, "STRIPE_WEBHOOK_SECRET", ""),
        getattr(config, "stripe_webhook_secret", "") if config else "",
    )


def _scrub(text: str, secret: str) -> str:
    cleaned = " ".join(str(text or "").split())
    if secret and len(secret) >= 4:
        cleaned = cleaned.replace(secret, "••••")
    return cleaned[:180]


def stripe_request(method: str, path: str, data=None, params=None) -> dict:
    secret = stripe_secret()
    if not secret:
        raise StripeNotConfigured("Stripe n'est pas configuré.")
    try:
        response = httpx.request(
            method,
            API + path,
            headers={"Authorization": f"Bearer {secret}"},
            data=data,
            params=params,
            timeout=20,
        )
    except httpx.HTTPError:
        raise StripeError("Stripe est injoignable.") from None
    if response.status_code >= 400:
        raise StripeError(_scrub(response.text, secret), status=response.status_code)
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        raise StripeError("Réponse Stripe illisible.") from None


def create_checkout_session(*, user, plan, success_url: str, cancel_url: str) -> dict:
    amount = int((plan.price_eur * 100).to_integral_value())
    if amount < 50:
        raise StripeError("Le montant du forfait est trop faible pour un paiement par carte.")
    payload = {
        "mode": "subscription",
        "locale": "fr",
        "customer_email": user.email,
        "client_reference_id": str(user.pk),
        "success_url": success_url,
        "cancel_url": cancel_url,
        "allow_promotion_codes": "false",
        "payment_method_types[0]": "card",
        "metadata[user_id]": str(user.pk),
        "metadata[plan_code]": plan.code,
        "subscription_data[metadata][user_id]": str(user.pk),
        "subscription_data[metadata][plan_code]": plan.code,
        "line_items[0][quantity]": 1,
        "line_items[0][price_data][currency]": "eur",
        "line_items[0][price_data][unit_amount]": amount,
        "line_items[0][price_data][recurring][interval]": "month",
        "line_items[0][price_data][product_data][name]": f"Road Runner Solutions — {plan.name}",
        "line_items[0][price_data][product_data][description]": (plan.description or plan.name)[:400],
    }
    trial = int(plan.trial_days or 0)
    if trial > 0:
        payload["subscription_data[trial_period_days]"] = trial
    session = stripe_request("POST", "/v1/checkout/sessions", data=payload)
    if not session.get("url"):
        raise StripeError("Stripe n'a pas renvoyé de page de paiement.")
    return session


def retrieve_checkout_session(session_id: str) -> dict:
    if not session_id or not session_id.startswith("cs_"):
        raise StripeError("Session de paiement inconnue.")
    return stripe_request("GET", f"/v1/checkout/sessions/{session_id}")


def cancel_subscription(subscription_id: str) -> None:
    if not subscription_id:
        return
    try:
        stripe_request("DELETE", f"/v1/subscriptions/{subscription_id}")
    except (StripeNotConfigured, StripeError):
        logger.info("Ancien abonnement Stripe non annulé (%s).", subscription_id[:8])


def retrieve_subscription(subscription_id: str) -> dict:
    if not subscription_id or not str(subscription_id).startswith("sub_"):
        raise StripeError("Abonnement Stripe inconnu.")
    return stripe_request("GET", f"/v1/subscriptions/{subscription_id}")


def list_invoices(*, subscription_id: str = "", limit: int = 24) -> list:
    if not subscription_id:
        return []
    payload = stripe_request(
        "GET",
        "/v1/invoices",
        params={"subscription": subscription_id, "limit": str(int(limit))},
    )
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, list) else []


def probe_balance() -> dict:
    secret = stripe_secret()
    if not secret:
        return {"ok": False, "message": "Stripe : non configuré."}
    try:
        stripe_request("GET", "/v1/balance")
    except StripeNotConfigured:
        return {"ok": False, "message": "Stripe : non configuré."}
    except StripeError as exc:
        if exc.status in (401, 403):
            return {"ok": False, "message": "Stripe : authentification refusée."}
        return {"ok": False, "message": "Échec de la connexion Stripe. " + exc.message}
    return {"ok": True, "message": "Connexion Stripe établie."}
