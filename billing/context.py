"""Contexte forfait pour les gabarits du cockpit."""
from __future__ import annotations


def forfait(request):
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return {"forfait": _open()}
    try:
        from billing.access import snapshot

        return {"forfait": snapshot(user)}
    except Exception:
        return {"forfait": _open()}


def _open():
    return {
        "open": True,
        "name": "",
        "code": "",
        "status": "",
        "past_due": False,
        "locks": {},
        "locked_themes": [],
        "can_invoice": True,
        "can_company": True,
    }
