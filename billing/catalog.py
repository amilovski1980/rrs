"""Catalogue des forfaits et matrice de fonctions réellement présentes dans l'application.

Les cases sont éditables dans le back-office (champ Plan.entitlements).
Un forfait sans matrice enregistrée reprend le palier déduit de son code
(Micro / Starter, Réel, Pro).
"""
from __future__ import annotations

from decimal import Decimal

from companies.models import INVOICE_THEMES

# Fonctions qui existent dans le cockpit ou l'agent. Pas de promesse hors produit.
BOOL_FEATURES = (
    ("entries", "Écritures comptables"),
    ("ledger", "Grand livre"),
    ("balance", "Balance"),
    ("invoices", "Factures"),
    ("invoice_pdf", "PDF facture, devis et avoir"),
    ("clients", "Fiches clients"),
    ("quotes", "Devis"),
    ("products", "Catalogue"),
    ("projects", "Projets"),
    ("credit_notes", "Avoirs"),
    ("payments", "Suivi des paiements"),
    ("invoice_import", "Import d'une facture PDF"),
    ("tickets", "Tickets de caisse et lecture de photo"),
    ("ai_chat", "Chat Aminia"),
    ("ai_voice", "Voix Aminia"),
    ("ai_drafts", "Brouillons IA à valider"),
)

THEME_CODES = tuple(code for code, _label in INVOICE_THEMES)

LIMITED_THEMES = ("azur", "carmin")
STANDARD_THEMES = ("azur", "carmin", "encre", "sauge")


def _flags(themes, **enabled):
    row = {key: False for key, _label in BOOL_FEATURES}
    row.update(enabled)
    row["themes"] = list(themes)
    return row


TIER_DEFAULTS = {
    "limited": _flags(
        LIMITED_THEMES,
        entries=True,
        ledger=True,
        balance=True,
        invoices=True,
        invoice_pdf=True,
        clients=True,
        ai_chat=True,
    ),
    "standard": _flags(
        STANDARD_THEMES,
        entries=True,
        ledger=True,
        balance=True,
        invoices=True,
        invoice_pdf=True,
        clients=True,
        quotes=True,
        products=True,
        projects=True,
        credit_notes=True,
        payments=True,
        invoice_import=True,
        ai_chat=True,
        ai_drafts=True,
    ),
    "full": _flags(
        THEME_CODES,
        **{key: True for key, _label in BOOL_FEATURES},
    ),
}


CATALOG = (
    {
        "code": "micro",
        "name": "Micro",
        "price_eur": Decimal("29.00"),
        "trial_days": 14,
        "description": "Pour démarrer : la comptabilité du quotidien, un volume de factures limité et le chat Aminia.",
        "max_companies": 1,
        "max_invoices_month": 20,
        "max_ai_requests_month": 40,
        "features": [
            "1 société",
            "Écritures, grand livre et balance",
            "20 factures par mois",
            "Clients et PDF",
            "Modèles Azur et Carmin",
            "Chat Aminia",
        ],
        "tier": "limited",
    },
    {
        "code": "reel",
        "name": "Réel",
        "price_eur": Decimal("49.00"),
        "trial_days": 14,
        "description": "Pour facturer au réel : devis, avoirs, catalogue, projets et plusieurs sociétés.",
        "max_companies": 3,
        "max_invoices_month": 80,
        "max_ai_requests_month": 200,
        "features": [
            "3 sociétés",
            "80 factures par mois",
            "Devis, avoirs et paiements",
            "Catalogue et projets",
            "Import PDF",
            "4 modèles de facture",
            "Brouillons IA",
        ],
        "tier": "standard",
    },
    {
        "code": "pro",
        "name": "Pro",
        "price_eur": Decimal("79.00"),
        "trial_days": 14,
        "description": "Tout le cockpit : voix Aminia, tickets de caisse, tous les modèles et sociétés illimitées.",
        "max_companies": None,
        "max_invoices_month": None,
        "max_ai_requests_month": None,
        "features": [
            "Sociétés illimitées",
            "Factures illimitées",
            "Tous les modèles de facture",
            "Tickets de caisse",
            "Voix Aminia",
            "Chat Aminia sans plafond",
        ],
        "tier": "full",
    },
)


def matrix_for_tier(tier: str) -> dict:
    base = TIER_DEFAULTS.get(tier) or TIER_DEFAULTS["limited"]
    return {"custom": True, **{key: bool(base[key]) for key, _label in BOOL_FEATURES}, "themes": list(base["themes"])}


def ensure_catalog():
    """Crée les forfaits manquants. Ne réécrit pas un forfait déjà présent."""
    from billing.models import Plan

    created = []
    for row in CATALOG:
        if Plan.objects.filter(code=row["code"]).exists():
            continue
        plan = Plan.objects.create(
            code=row["code"],
            name=row["name"],
            price_eur=row["price_eur"],
            trial_days=row["trial_days"],
            description=row["description"],
            max_companies=row["max_companies"],
            max_invoices_month=row["max_invoices_month"],
            max_ai_requests_month=row["max_ai_requests_month"],
            features=list(row["features"]),
            entitlements=matrix_for_tier(row["tier"]),
            is_active=True,
        )
        created.append(plan)
    return created
