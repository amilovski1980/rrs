"""Application idempotente des événements Stripe sur l'abonnement local."""
from __future__ import annotations

from datetime import datetime, timezone as dt_timezone

from django.db import transaction
from django.utils import timezone

from accounts.models import User

from .models import Plan, Subscription
from .stripe_api import cancel_subscription

STRIPE_STATUS = {
    "active": "active",
    "trialing": "trialing",
    "past_due": "past_due",
    "unpaid": "past_due",
    "canceled": "canceled",
    "incomplete": "past_due",
    "incomplete_expired": "canceled",
    "paused": "past_due",
}


def _as_id(value):
    if isinstance(value, dict):
        return value.get("id") or ""
    return value or ""


def _period_end(timestamp):
    if not timestamp:
        return None
    try:
        moment = datetime.fromtimestamp(int(timestamp), tz=dt_timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
    if timezone.is_naive(moment):
        return timezone.make_aware(moment, dt_timezone.utc)
    return moment


def _upsert(user, plan, status, stripe_sub_id, customer_id, period_end):
    row = None
    if stripe_sub_id:
        row = Subscription.objects.filter(stripe_subscription_id=stripe_sub_id).first()
    if row is None:
        row = Subscription.objects.filter(user=user).order_by("-created_at").first()
    if row is not None and row.user_id != user.id:
        row = None
    previous = row.stripe_subscription_id if row is not None else ""
    if row is None:
        row = Subscription(user=user, plan=plan)
    row.plan = plan
    row.status = status
    if stripe_sub_id:
        row.stripe_subscription_id = stripe_sub_id[:50]
    if customer_id:
        row.stripe_customer_id = str(customer_id)[:50]
    if period_end is not None:
        row.current_period_end = period_end
    row.save()
    if previous and stripe_sub_id and previous != stripe_sub_id and status in ("active", "trialing"):
        cancel_subscription(previous)
    return row


def apply_checkout_session(session: dict) -> bool:
    if not isinstance(session, dict):
        return False
    if session.get("mode") not in (None, "", "subscription"):
        return False
    metadata = session.get("metadata") or {}
    user_id = session.get("client_reference_id") or metadata.get("user_id")
    plan_code = metadata.get("plan_code") or ""
    user = User.objects.filter(pk=user_id).first() if user_id else None
    plan = Plan.objects.filter(code=plan_code).first() if plan_code else None
    if user is None or plan is None:
        return False
    payment_status = session.get("payment_status") or "paid"
    if payment_status == "unpaid":
        status = "past_due"
    elif payment_status == "no_payment_required":
        status = "trialing"
    else:
        status = "active"
    _upsert(
        user,
        plan,
        status,
        _as_id(session.get("subscription")),
        _as_id(session.get("customer")),
        None,
    )
    return True


def apply_subscription_object(obj: dict, *, deleted: bool = False) -> bool:
    if not isinstance(obj, dict):
        return False
    metadata = obj.get("metadata") or {}
    stripe_sub_id = obj.get("id") or ""
    user = User.objects.filter(pk=metadata.get("user_id")).first() if metadata.get("user_id") else None
    existing = None
    if stripe_sub_id:
        existing = Subscription.objects.filter(stripe_subscription_id=stripe_sub_id).select_related("plan").first()
    if user is None and existing is not None:
        user = existing.user
    plan = Plan.objects.filter(code=metadata.get("plan_code")).first() if metadata.get("plan_code") else None
    if plan is None and existing is not None:
        plan = existing.plan
    if user is None or plan is None:
        return False
    if deleted:
        status = "canceled"
    else:
        status = STRIPE_STATUS.get(obj.get("status") or "", "past_due")
    _upsert(
        user,
        plan,
        status,
        stripe_sub_id,
        _as_id(obj.get("customer")),
        _period_end(obj.get("current_period_end")),
    )
    return True


def apply_payment_failed(invoice: dict) -> bool:
    sub_id = _as_id(invoice.get("subscription") if isinstance(invoice, dict) else None)
    if not sub_id:
        return False
    updated = Subscription.objects.filter(stripe_subscription_id=sub_id).update(status="past_due")
    return bool(updated)


def dispatch_event(event: dict) -> None:
    kind = (event or {}).get("type") or ""
    data = ((event or {}).get("data") or {}).get("object") or {}
    if kind == "checkout.session.completed":
        apply_checkout_session(data)
    elif kind == "customer.subscription.updated":
        apply_subscription_object(data, deleted=False)
    elif kind == "customer.subscription.deleted":
        apply_subscription_object(data, deleted=True)
    elif kind == "invoice.payment_failed":
        apply_payment_failed(data)


def record_and_apply(event: dict) -> bool:
    """True si l'événement est nouveau et appliqué. False s'il a déjà été vu."""
    from billing.models import StripeEvent

    event_id = (event or {}).get("id") or ""
    if not event_id:
        raise ValueError("Événement sans identifiant.")
    kind = ((event or {}).get("type") or "")[:40]
    with transaction.atomic():
        if StripeEvent.objects.filter(external_id=event_id).exists():
            return False
        StripeEvent.objects.create(external_id=event_id[:60], type=kind, payload=event)
        dispatch_event(event)
    return True
