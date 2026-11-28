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


def public_theme_context(request) -> dict:
    """Préfixe des liens de la vitrine publique.

    Le thème sombre est officiel : à la racine, les liens du parcours
    (connexion, inscription, démo) pointent vers /dark pour rester dans le
    même habillage. Sous /dark, Django ajoute déjà le préfixe aux {% url %}.
    """
    dark = bool(getattr(request, "dark_ui", False))
    return {"public_dark_prefix": "" if dark else "/dark", "public_dark_path": dark}


def public_appearance_context(request) -> dict:
    """Logos, wordmarks et textes d'accueil disponibles sur toutes les pages publiques."""
    try:
        from admin_backoffice.models import SiteConfiguration

        config = SiteConfiguration.objects.filter(pk=1).first()
    except Exception:
        config = None
    accent = (getattr(config, "site_accent", "") or "").strip()
    accent = accent if accent.startswith("#") and len(accent) in (4, 7) else ""
    return {
        "site_accent": accent,
        "site_accent_light": _readable_on_light(accent) if accent else "",
        "home_title": (getattr(config, "home_title", "") or "").strip(),
        "home_subtitle": (getattr(config, "home_subtitle", "") or "").strip(),
        "has_logo_dark": bool(getattr(config, "logo_dark", None)),
        "has_logo_light": bool(getattr(config, "logo_light", None)),
        "has_wordmark_dark": bool(getattr(config, "wordmark_dark", None)),
        "has_wordmark_light": bool(getattr(config, "wordmark_light", None)),
    }


def _readable_on_light(hex_color: str) -> str:
    value = (hex_color or "").strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        return hex_color
    try:
        red, green, blue = (int(value[index:index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        return hex_color
    factor = 0.55
    return "#{:02x}{:02x}{:02x}".format(int(red * factor), int(green * factor), int(blue * factor))



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
