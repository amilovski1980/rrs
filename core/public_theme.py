"""Vitrine publique alternative, servie sous /dark.

Les vues restent celles du parcours classique. Seuls le gabarit, les URLs
internes et la voix des textes changent. Le cockpit connecté n'est pas concerné.
"""
from __future__ import annotations

from django.shortcuts import redirect
from django.urls import reverse

DARK_NAMESPACE = "dark"

PUBLIC_NAMES = frozenset({
    "landing",
    "company_search",
    "signup_wizard",
    "signup_start",
    "signup_pending",
    "signup_verify",
    "signup_phone_check",
    "magic_link_request",
    "magic_link_email",
    "magic_link_email_done",
    "magic_link_verify",
    "password_reset",
    "password_reset_done",
    "password_reset_confirm",
    "password_reset_complete",
})

# Voix startups. On ne remplace une accroche publiée que si elle est vide
# ou encore égale au catalogue par défaut : un texte saisi dans le back-office reste.
DARK_BLURBS = {
    "micro": "Pour ouvrir la boîte : une société, les factures du quotidien, le chat Aminia.",
    "reel": "Quand les devis s'enchaînent : plusieurs sociétés, avoirs, catalogue et projets.",
    "pro": "Tout le cockpit, sans plafond. Voix Aminia, tickets, autant de sociétés que vous ouvrez.",
}


def is_dark(request) -> bool:
    match = getattr(request, "resolver_match", None)
    return bool(match and match.namespace == DARK_NAMESPACE)


def themed_template(request, template_name: str) -> str:
    if is_dark(request):
        return f"dark/{template_name}"
    return template_name


def themed_reverse(request, viewname: str, *args, **kwargs) -> str:
    if is_dark(request) and viewname in PUBLIC_NAMES:
        viewname = f"{DARK_NAMESPACE}:{viewname}"
    return reverse(viewname, args=args, kwargs=kwargs)


def themed_redirect(request, viewname: str, *args, **kwargs):
    return redirect(themed_reverse(request, viewname, *args, **kwargs))


def with_dark_voice(context: dict) -> dict:
    """Même faits (prix, plafonds, matrice), autre phrase d'accroche."""
    from billing.catalog import CATALOG

    defaults = {(row.get("code") or "").lower(): (row.get("description") or "").strip() for row in CATALOG}
    cards = []
    for card in context.get("pricing_cards") or []:
        updated = dict(card)
        code = (updated.get("code") or "").lower()
        current = (updated.get("description") or "").strip()
        blurb = DARK_BLURBS.get(code)
        if blurb and (not current or current == defaults.get(code, "")):
            updated["description"] = blurb
        updated["cta"] = "Je me lance" if updated.get("recommended") else "Choisir"
        cards.append(updated)
    themed = dict(context)
    themed["pricing_cards"] = cards
    themed["pricing_trial_line"] = _relaxed_trial(context.get("pricing_trial_line") or "")
    return themed


def _relaxed_trial(line: str) -> str:
    prefix = "Sans carte bancaire · essai "
    if line.startswith(prefix):
        return "Sans carte bancaire · " + line[len(prefix):] + " pour tester"
    return line
