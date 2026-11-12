"""Habillage /dark.

Les vues restent celles du parcours classique. Le middleware DarkMount sert
les mêmes URLs sous /dark et préfixe les liens. Les gabarits publics dédiés
et la voix de la vitrine ne s'appliquent qu'aux pages d'entrée.
"""
from __future__ import annotations

from django.shortcuts import redirect
from django.urls import reverse

DARK_NAMESPACE = "dark"

# Voix startups. On ne remplace une accroche publiée que si elle est vide
# ou encore égale au catalogue par défaut : un texte saisi dans le back-office reste.
DARK_BLURBS = {
    "micro": "Pour ouvrir la boîte : une société, les factures du quotidien, le chat Aminia.",
    "reel": "Quand les devis s'enchaînent : plusieurs sociétés, avoirs, catalogue et projets.",
    "pro": "Tout le cockpit, sans plafond. Voix Aminia, tickets, autant de sociétés que vous ouvrez.",
}


def is_dark(request) -> bool:
    if getattr(request, "dark_ui", False):
        return True
    match = getattr(request, "resolver_match", None)
    return bool(match and match.namespace == DARK_NAMESPACE)


def themed_template(request, template_name: str) -> str:
    if is_dark(request):
        return f"dark/{template_name}"
    return template_name


def themed_reverse(request, viewname: str, *args, **kwargs) -> str:
    # Le préfixe /dark est ajouté par le script prefix pendant la requête.
    # Filet de sécurité si un appel arrive sans ce préfixe.
    url = reverse(viewname, args=args, kwargs=kwargs)
    if is_dark(request) and url.startswith("/") and not url.startswith("/dark/") and not url.startswith("//"):
        return "/dark" + url
    return url


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
