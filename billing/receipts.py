"""Reçus d'abonnement enregistrés à partir des événements Stripe.

Les webhooks restent idempotents : un même événement n'est appliqué qu'une
fois (StripeEvent), et un même identifiant de facture Stripe met à jour la
même ligne locale.
"""
from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from .models import Subscription, SubscriptionInvoice
from .services import _as_id, _period_end

ATTENTION = ("past_due", "unpaid")


def _public_text(value, limit=400) -> str:
    text = " ".join(str(value or "").split())
    lowered = text.lower()
    if any(marker in lowered for marker in ("sk_live", "sk_test", "whsec_", "rk_live", "rk_test")):
        return ""
    return text[:limit]


def _euros(cents, fallback: Decimal) -> Decimal:
    if cents is None:
        return fallback
    try:
        return (Decimal(int(cents)) / Decimal("100")).quantize(Decimal("0.01"))
    except (TypeError, ValueError, ArithmeticError):
        return fallback


def _invoice_status(invoice: dict, *, failed: bool) -> str:
    if failed:
        return "failed"
    raw = (invoice.get("status") or "").strip()
    if raw in dict(SubscriptionInvoice.STATUSES):
        return raw
    if invoice.get("paid"):
        return "paid"
    return "open"


def _find_subscription(invoice: dict):
    sub_id = _as_id(invoice.get("subscription"))
    if sub_id:
        row = (
            Subscription.objects.filter(stripe_subscription_id=sub_id)
            .select_related("user", "plan")
            .first()
        )
        if row is not None:
            return row
    customer = _as_id(invoice.get("customer"))
    if not customer:
        return None
    return (
        Subscription.objects.filter(stripe_customer_id=customer)
        .select_related("user", "plan")
        .order_by("-created_at")
        .first()
    )


def _hosted(url: str) -> str:
    cleaned = _public_text(url, limit=500)
    if not cleaned.startswith("https://"):
        return ""
    return cleaned


def record_invoice_receipt(invoice: dict, *, failed: bool = False, touch_follow_up: bool = True):
    if not isinstance(invoice, dict):
        return None
    subscription = _find_subscription(invoice)
    if subscription is None:
        return None
    sub_id = _as_id(invoice.get("subscription")) or subscription.stripe_subscription_id or "local"
    external = (invoice.get("id") or "").strip()
    if not external:
        external = f"local-fail-{sub_id}" if failed else f"local-paid-{sub_id}"
    paid = bool(invoice.get("paid") or invoice.get("status") == "paid")
    cents = invoice.get("amount_paid") if paid else invoice.get("amount_due")
    if cents is None:
        cents = invoice.get("total") if invoice.get("total") is not None else invoice.get("amount_total")
    amount = _euros(cents, subscription.plan.price_eur)
    status = _invoice_status(invoice, failed=failed)
    issued = _period_end(invoice.get("created")) or timezone.now()
    transitions = invoice.get("status_transitions") if isinstance(invoice.get("status_transitions"), dict) else {}
    paid_at = _period_end(transitions.get("paid_at")) if status == "paid" else None
    if status == "paid" and paid_at is None:
        paid_at = timezone.now()
    description = _public_text(invoice.get("description"), limit=255)
    if not description:
        description = f"Abonnement {subscription.plan.name}"[:255]
    failure = ""
    if failed or status == "failed":
        err = invoice.get("last_payment_error") or invoice.get("last_finalization_error") or {}
        if isinstance(err, dict):
            failure = _public_text(err.get("message"), limit=400)
        else:
            failure = _public_text(err, limit=400)
    row = SubscriptionInvoice.objects.filter(external_id=external[:80]).first()
    if row is None:
        row = SubscriptionInvoice(external_id=external[:80], user=subscription.user, issued_at=issued)
    row.user = subscription.user
    row.subscription = subscription
    row.number = _public_text(invoice.get("number"), limit=40)
    row.amount_eur = amount
    row.status = status
    row.description = description
    if failure:
        row.failure_message = failure
    hosted = _hosted(invoice.get("hosted_invoice_url") or "")
    if hosted:
        row.hosted_url = hosted
    if paid_at is not None:
        row.paid_at = paid_at
    row.save()
    if touch_follow_up:
        if failed and subscription.follow_up != "reminded" and subscription.follow_up != "to_follow":
            subscription.follow_up = "to_follow"
            subscription.save(update_fields=["follow_up"])
        elif status == "paid" and subscription.follow_up == "to_follow":
            subscription.follow_up = "resolved"
            subscription.save(update_fields=["follow_up"])
    return row


def record_checkout_receipt(session: dict):
    if not isinstance(session, dict):
        return None
    payment = session.get("payment_status") or ""
    if payment not in ("paid", "unpaid"):
        return None
    external = _as_id(session.get("invoice")) or (session.get("id") or "")
    if not external:
        return None
    shaped = {
        "id": external,
        "subscription": session.get("subscription"),
        "customer": session.get("customer"),
        "amount_due": session.get("amount_total"),
        "amount_paid": session.get("amount_total") if payment == "paid" else None,
        "paid": payment == "paid",
        "status": "paid" if payment == "paid" else "open",
        "created": session.get("created"),
        "description": "",
        "metadata": session.get("metadata") or {},
    }
    if payment == "paid":
        shaped["status_transitions"] = {"paid_at": session.get("created")}
    return record_invoice_receipt(shaped, failed=payment == "unpaid")


def mark_paid_subscription(invoice: dict):
    """Un encaissement réussi sort le compte du retard, sans réactiver une résiliation."""
    sub_id = _as_id(invoice.get("subscription") if isinstance(invoice, dict) else None)
    if not sub_id:
        return
    Subscription.objects.filter(
        stripe_subscription_id=sub_id,
        status__in=list(ATTENTION),
    ).update(status="active", follow_up="resolved")
