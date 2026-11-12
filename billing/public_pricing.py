"""Forfaits affichés sur la vitrine publique.

Les forfaits publiés (is_active) viennent de la base : prix, plafonds et
matrice de fonctions. Si la table est vide ou illisible, on reprend le
catalogue par défaut, sans rien écrire. Des forfaits présents mais non
publiés ne sont pas remplacés par ce catalogue.

Plan.price_eur est le montant mensuel envoyé à Stripe en unit_amount,
sans tax_behavior et sans taxe automatique (billing.stripe_api).
Le client est débité de ce montant exact : ce n'est pas un hors-taxe
auquel 20 % seraient ajoutés. Pour un public professionnel, le prix est
affiché HT et la mention précise que le débit est égal au prix affiché.
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

from django.db import DatabaseError

from companies.models import INVOICE_THEMES

from .access import _plan_matrix
from .catalog import CATALOG, matrix_for_tier

logger = logging.getLogger(__name__)

RECOMMENDED_CODE = "reel"
CTA_HREF = "#recherche"
PRICE_TAX_NOTE = (
    "Tarifs mensuels hors taxes, pour les professionnels. "
    "Le montant débité correspond au prix affiché."
)


def pricing_context() -> dict:
    cards = public_plan_cards()
    return {
        "pricing_cards": cards,
        "pricing_tax_note": PRICE_TAX_NOTE,
        "pricing_trial_line": trial_headline(cards),
    }


def public_plan_cards() -> list[dict]:
    """Forfaits publiés. Catalogue par défaut seulement si la base n'en a aucun."""
    loaded = _load_plans()
    if loaded is None:
        plans = _fallback_plans()
    else:
        published, any_plan = loaded
        if published:
            plans = published
        elif not any_plan:
            plans = _fallback_plans()
        else:
            plans = []
    return [_card(plan) for plan in plans]


def trial_headline(cards) -> str:
    days = {card["trial_days"] for card in cards if card.get("trial_days")}
    if len(days) == 1:
        day = next(iter(days))
        unit = "jour" if day == 1 else "jours"
        return f"Sans carte bancaire · essai {day} {unit}"
    if days:
        return "Sans carte bancaire · essai gratuit"
    return "Sans carte bancaire"


def format_price_eur(amount) -> str:
    try:
        value = Decimal(amount).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return "— €"
    sign = "−" if value < 0 else ""
    value = abs(value)
    whole = int(value)
    cents = int((value * 100) % 100)
    grouped = f"{whole:,}".replace(",", " ")
    if cents:
        return f"{sign}{grouped},{cents:02d} €"
    return f"{sign}{grouped} €"


def limit_lines(plan) -> list[str]:
    return [
        _quota(getattr(plan, "max_companies", None), "société", "sociétés", "Sociétés illimitées"),
        _quota(
            getattr(plan, "max_invoices_month", None),
            "facture / mois",
            "factures / mois",
            "Factures illimitées",
        ),
        _quota(
            getattr(plan, "max_ai_requests_month", None),
            "message Aminia / mois",
            "messages Aminia / mois",
            "Messages Aminia illimités",
        ),
    ]


def included_lines(matrix: dict | None) -> list[str]:
    matrix = matrix if isinstance(matrix, dict) else {}
    lines: list[str] = []
    accounting = _picked(
        matrix,
        (("entries", "écritures"), ("ledger", "grand livre"), ("balance", "balance")),
    )
    if accounting:
        lines.append(_sentence(accounting))
    billing = _picked(matrix, (("invoices", "factures"), ("clients", "clients"), ("invoice_pdf", "PDF")))
    if billing:
        lines.append(_sentence(billing))
    themes = _theme_line(matrix.get("themes"))
    if themes:
        lines.append(themes)
    commercial = _picked(matrix, (("quotes", "devis"), ("products", "catalogue"), ("projects", "projets")))
    if commercial:
        lines.append(_sentence(commercial))
    settlement = _picked(
        matrix,
        (("credit_notes", "avoirs"), ("payments", "paiements"), ("invoice_import", "import PDF")),
    )
    if settlement:
        lines.append(_sentence(settlement))
    if matrix.get("ai_drafts"):
        lines.append("Brouillons IA")
    if matrix.get("tickets"):
        lines.append("Tickets de caisse")
    if matrix.get("ai_voice"):
        lines.append("Voix Aminia")
    if matrix.get("ai_chat"):
        lines.append("Chat Aminia")
    return lines


def _load_plans():
    """(publiés, au moins un forfait en base), ou None si la base est illisible."""
    from billing.models import Plan

    try:
        rows = list(Plan.objects.order_by("price_eur", "name"))
    except DatabaseError as exc:
        logger.warning(
            "Lecture des forfaits impossible (%s), catalogue par défaut.",
            exc.__class__.__name__,
        )
        return None
    return [plan for plan in rows if plan.is_active], bool(rows)


def _fallback_plans():
    plans = []
    for row in CATALOG:
        plans.append(SimpleNamespace(
            code=row["code"],
            name=row["name"],
            price_eur=row["price_eur"],
            description=row["description"],
            max_companies=row["max_companies"],
            max_invoices_month=row["max_invoices_month"],
            max_ai_requests_month=row["max_ai_requests_month"],
            trial_days=row["trial_days"],
            entitlements=matrix_for_tier(row["tier"]),
            is_active=True,
        ))
    return plans


def _card(plan) -> dict:
    code = (getattr(plan, "code", "") or "").strip()
    recommended = code.lower() == RECOMMENDED_CODE
    trial = getattr(plan, "trial_days", 0) or 0
    try:
        trial = int(trial)
    except (TypeError, ValueError):
        trial = 0
    description = (getattr(plan, "description", "") or "").strip()
    return {
        "code": code,
        "name": getattr(plan, "name", "") or code,
        "price_label": format_price_eur(getattr(plan, "price_eur", None)),
        "description": description,
        "limits": limit_lines(plan),
        "features": included_lines(_plan_matrix(plan)),
        "recommended": recommended,
        "trial_days": trial,
        "cta": "Commencer l'essai" if recommended else "Commencer",
        "cta_href": CTA_HREF,
    }


def _quota(value, singular: str, plural: str, unlimited: str) -> str:
    if value is None or value == "":
        return unlimited
    try:
        number = int(value)
    except (TypeError, ValueError):
        return unlimited
    if number == 1:
        return f"1 {singular}"
    return f"{number} {plural}"


def _picked(matrix: dict, pairs) -> list[str]:
    return [label for key, label in pairs if matrix.get(key)]


def _sentence(parts: list[str]) -> str:
    text = _join_fr(parts)
    return text[0].upper() + text[1:] if text else ""


def _join_fr(parts: list[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} et {parts[1]}"
    return ", ".join(parts[:-1]) + " et " + parts[-1]


def _theme_line(codes) -> str:
    if not isinstance(codes, list):
        return ""
    labels = dict(INVOICE_THEMES)
    names = [labels[code] for code in codes if code in labels]
    if not names:
        return ""
    if len(names) == len(INVOICE_THEMES):
        return f"Les {len(names)} modèles de facture"
    if len(names) == 1:
        return f"Modèle {names[0]}"
    return "Modèles " + _join_fr(names)
