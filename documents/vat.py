"""TVA française et intracommunautaire : validation et mentions légales.

Le numéro de TVA intracommunautaire français se calcule depuis le SIREN :
clé = (12 + 3 × (SIREN modulo 97)) modulo 97. Les autres pays de l'UE ont
leurs propres formats : on ne valide ici que la forme générale du préfixe.
"""
from __future__ import annotations

import re
from decimal import Decimal

# Préfixes des États membres de l'Union européenne.
EU_VAT_PREFIXES = {
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR",
    "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO",
    "SE", "SI", "SK", "XI",
}

FRENCH_VAT_RE = re.compile(r"^FR\d{11}$")
EU_VAT_RE = re.compile(r"^(?:%s)[0-9A-Z]{2,14}$" % "|".join(sorted(EU_VAT_PREFIXES)))

REVERSE_CHARGE_MENTION = (
    "Autoliquidation de la TVA — TVA due par le preneur "
    "(article 283-2 du CGI)."
)
FRANCHISE_MENTION = "TVA non applicable, article 293 B du CGI."


def digits(value) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def french_vat_from_siren(siren: str) -> str:
    """Retourne le numéro français compact (FR + clé + SIREN), ou une chaîne vide."""
    siren = digits(siren)
    if len(siren) != 9:
        return ""
    key = (12 + 3 * (int(siren) % 97)) % 97
    return f"FR{key:02d}{siren}"


def normalize_vat_number(value) -> str:
    """Retire espaces, points et tirets ; met le préfixe en majuscules."""
    text = re.sub(r"[\s.\-]", "", str(value or "")).upper()
    return text


def is_valid_vat_number(value) -> bool:
    compact = normalize_vat_number(value)
    if not compact:
        return True
    if FRENCH_VAT_RE.match(compact):
        return True
    return bool(EU_VAT_RE.match(compact))


def format_vat_number(value) -> str:
    """Affichage lisible : FR17100408517 -> FR 17 100 408 517."""
    compact = normalize_vat_number(value)
    if FRENCH_VAT_RE.match(compact):
        return f"{compact[:2]} {compact[2:4]} {compact[4:7]} {compact[7:10]} {compact[10:]}"
    return compact


def vat_mentions(document, company) -> list[str]:
    """Mentions de TVA à imprimer sur le document, dans l'ordre légal."""
    mentions: list[str] = []
    reverse_charge = bool(getattr(document, "reverse_charge", False))
    if reverse_charge:
        mentions.append(REVERSE_CHARGE_MENTION)
    reason = str(getattr(document, "vat_exemption_reason", "") or "").strip()
    if reason and reason not in mentions:
        mentions.append(reason)
    vat_rate = Decimal(str(getattr(document, "vat_rate", 0) or 0))
    if (
        not reverse_charge
        and not reason
        and getattr(company, "tva", "") == "franchise"
        and vat_rate == 0
    ):
        mentions.append(FRANCHISE_MENTION)
    return mentions
