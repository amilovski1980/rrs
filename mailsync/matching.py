"""Rapprochement fournisseur : SIRET > TVA > domaine e-mail > nom."""

from __future__ import annotations

import re

from .models import Supplier


def normalize_siret(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def normalize_vat(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value or "").upper()


def email_domain(email: str) -> str:
    _, _, domain = (email or "").rpartition("@")
    return domain.lower().strip(".")


def find_matching_supplier(
    company, *, name: str = "", siret: str = "", vat: str = "", email: str = ""
) -> Supplier | None:
    """Cherche un fournisseur existant, du signal le plus fiable au plus flou."""
    siret = normalize_siret(siret)
    vat = normalize_vat(vat)
    domain = email_domain(email)

    if siret:
        found = Supplier.objects.filter(company=company, siret=siret).first()
        if found:
            return found
    if vat:
        found = Supplier.objects.filter(company=company, tva_intra__iexact=vat).first()
        if found:
            return found
    if domain:
        found = Supplier.objects.filter(company=company, email_domain=domain).first()
        if found:
            return found
    if name:
        found = Supplier.objects.filter(company=company, name__iexact=name.strip()).first()
        if found:
            return found
    return None


def create_supplier(
    company,
    *,
    name: str,
    siret: str = "",
    vat: str = "",
    email: str = "",
    charge_code: str = "",
    source: str = "mailsync",
) -> Supplier:
    """Crée un fournisseur (validation en un clic depuis l'écran de contrôle)."""
    return Supplier.objects.create(
        company=company,
        name=(name or "Fournisseur").strip()[:200],
        siret=normalize_siret(siret),
        tva_intra=normalize_vat(vat),
        email=(email or "").strip()[:254],
        email_domain=email_domain(email),
        default_charge_code=(charge_code or "").strip()[:10],
        created_from=source,
    )
