"""Lecture de la matrice de forfait et décisions d'accès.

Sans abonnement, le cockpit historique reste ouvert : les comptes déjà en
prise en main et les tests ne sont pas coupés. Dès qu'un abonnement existe,
la matrice du forfait s'applique. Un abonnement résilié retombe sur le
palier d'entrée.
"""
from __future__ import annotations

from django.utils import timezone

from admin_backoffice.agent_prompts import tier_for_plan

from .catalog import BOOL_FEATURES, THEME_CODES, TIER_DEFAULTS

UPGRADE_MESSAGE = (
    "Cette fonction n'est pas incluse dans votre forfait. "
    "Mettez à jour le forfait pour la débloquer."
)
QUOTA_INVOICE = (
    "Vous avez atteint le nombre de factures inclus dans votre forfait ce mois-ci. "
    "Mettez à jour le forfait pour continuer."
)
QUOTA_AI = (
    "Vous avez atteint le nombre de messages Aminia inclus dans votre forfait ce mois-ci. "
    "Mettez à jour le forfait pour continuer."
)
QUOTA_COMPANY = (
    "Votre forfait ne permet pas d'ajouter une autre société. "
    "Mettez à jour le forfait pour la débloquer."
)


def _plan_matrix(plan) -> dict:
    tier = tier_for_plan(plan) if plan is not None else "limited"
    base = TIER_DEFAULTS.get(tier) or TIER_DEFAULTS["limited"]
    resolved = {key: bool(base[key]) for key, _label in BOOL_FEATURES}
    resolved["themes"] = list(base["themes"])
    stored = getattr(plan, "entitlements", None) if plan is not None else None
    if not isinstance(stored, dict) or not stored:
        return resolved
    if stored.get("custom"):
        for key, _label in BOOL_FEATURES:
            resolved[key] = bool(stored.get(key))
        themes = stored.get("themes") if isinstance(stored.get("themes"), list) else []
        cleaned = [code for code in themes if code in THEME_CODES]
        resolved["themes"] = cleaned or list(base["themes"])
        return resolved
    for key, _label in BOOL_FEATURES:
        if key in stored:
            resolved[key] = bool(stored[key])
    if isinstance(stored.get("themes"), list) and stored["themes"]:
        cleaned = [code for code in stored["themes"] if code in THEME_CODES]
        if cleaned:
            resolved["themes"] = cleaned
    return resolved


def latest_subscription(user):
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    from billing.models import Subscription

    return (
        Subscription.objects.filter(user=user)
        .select_related("plan")
        .order_by("-created_at")
        .first()
    )


def govern(user) -> dict:
    """mode open | plan | lapsed."""
    subscription = latest_subscription(user)
    if subscription is None:
        return {"mode": "open", "subscription": None, "plan": None}
    if subscription.status in ("active", "trialing", "past_due"):
        return {"mode": "plan", "subscription": subscription, "plan": subscription.plan}
    return {"mode": "lapsed", "subscription": subscription, "plan": subscription.plan}


def matrix_for_user(user) -> dict | None:
    """None = pas de bride (aucun abonnement)."""
    state = govern(user)
    if state["mode"] == "open":
        return None
    if state["mode"] == "lapsed":
        limited = TIER_DEFAULTS["limited"]
        return {key: bool(limited[key]) for key, _label in BOOL_FEATURES} | {
            "themes": list(limited["themes"])
        }
    return _plan_matrix(state["plan"])


def feature_on(user, key: str) -> bool:
    matrix = matrix_for_user(user)
    if matrix is None:
        return True
    return bool(matrix.get(key))


def allowed_themes(user) -> list[str] | None:
    """None = tous les modèles."""
    matrix = matrix_for_user(user)
    if matrix is None:
        return None
    return list(matrix.get("themes") or [])


def theme_allowed(user, code: str) -> bool:
    allowed = allowed_themes(user)
    if allowed is None:
        return True
    return code in allowed


def _month_start():
    now = timezone.now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _cap(plan, field: str):
    if plan is None:
        return None
    value = getattr(plan, field, None)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def invoice_usage(user) -> int:
    from documents.models import Invoice

    return Invoice.objects.filter(company__owner=user, created_at__gte=_month_start()).count()


def invoice_create_block(user) -> str | None:
    if not feature_on(user, "invoices"):
        return UPGRADE_MESSAGE
    state = govern(user)
    if state["mode"] == "lapsed":
        if invoice_usage(user) >= 20:
            return QUOTA_INVOICE
        return None
    if state["mode"] != "plan":
        return None
    cap = _cap(state["plan"], "max_invoices_month")
    if cap is None:
        return None
    if invoice_usage(user) >= cap:
        return QUOTA_INVOICE
    return None


def company_count(user) -> int:
    from companies.models import Company

    return Company.objects.filter(owner=user).count()


def company_create_block(user) -> str | None:
    state = govern(user)
    if state["mode"] == "open":
        return None
    if state["mode"] == "lapsed":
        cap = 1
    else:
        cap = _cap(state["plan"], "max_companies")
    if cap is None:
        return None
    if company_count(user) >= cap:
        return QUOTA_COMPANY
    return None


def ai_usage(user) -> int:
    from ai.models import Message

    return Message.objects.filter(
        conversation__user=user, role="user", created_at__gte=_month_start()
    ).count()


def ai_quota_block(user) -> str | None:
    if not feature_on(user, "ai_chat"):
        return UPGRADE_MESSAGE
    state = govern(user)
    if state["mode"] != "plan":
        return None
    cap = _cap(state["plan"], "max_ai_requests_month")
    if cap is None:
        return None
    if ai_usage(user) >= cap:
        return QUOTA_AI
    return None


def snapshot(user) -> dict:
    """Contexte d'interface : rien n'est masqué, les cadenas sont explicites."""
    locks = {key: False for key, _label in BOOL_FEATURES}
    locks["extra_company"] = False
    state = govern(user)
    base = {
        "open": state["mode"] == "open",
        "name": "",
        "code": "",
        "status": "",
        "past_due": False,
        "locks": locks,
        "locked_themes": [],
        "can_invoice": True,
        "can_company": True,
    }
    if state["mode"] == "open":
        return base
    plan = state["plan"]
    matrix = matrix_for_user(user) or {}
    for key, _label in BOOL_FEATURES:
        locks[key] = not bool(matrix.get(key))
    allowed = set(matrix.get("themes") or [])
    locked_themes = [code for code in THEME_CODES if code not in allowed]
    company_block = company_create_block(user)
    locks["extra_company"] = bool(company_block)
    base.update({
        "open": False,
        "name": plan.name if plan else "",
        "code": plan.code if plan else "",
        "status": state["subscription"].status if state["subscription"] else "",
        "past_due": bool(state["subscription"] and state["subscription"].status == "past_due"),
        "locks": locks,
        "locked_themes": locked_themes,
        "can_invoice": invoice_create_block(user) is None,
        "can_company": company_block is None,
    })
    return base
