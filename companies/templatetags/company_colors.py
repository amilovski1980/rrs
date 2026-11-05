"""Couleurs distinctes et stables pour les cartes société du cockpit."""
from __future__ import annotations

import hashlib

from django import template

register = template.Library()

PALETTE_SIZE = 10


def _hash_index(company) -> int:
    raw = str(getattr(company, "pk", None) or getattr(company, "id", "") or "")
    if not raw:
        raw = (getattr(company, "denomination", "") or "") + (getattr(company, "siren", "") or "")
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % PALETTE_SIZE


@register.simple_tag
def company_color_class(company, companies=None) -> str:
    """Classe .co-c0 … .co-c9.

    Préfère l'index dans la liste des sociétés de l'utilisateur (couleurs
    distinctes entre elles), sinon un hash stable de l'id.
    """
    if companies is not None:
        try:
            seq = list(companies)
            for i, other in enumerate(seq):
                if getattr(other, "pk", None) == getattr(company, "pk", None):
                    return f"co-c{i % PALETTE_SIZE}"
        except TypeError:
            pass
    return f"co-c{_hash_index(company)}"


@register.filter
def company_initial(company) -> str:
    name = (getattr(company, "denomination", None) or "").strip()
    return (name[:1] or "?").upper()
