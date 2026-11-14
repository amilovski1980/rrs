"""Extraction et pré-sélection depuis le libellé d'une opération bancaire."""
from __future__ import annotations

import re

from .utils import normalize_text

REFERENCE_RE = re.compile(r"\b\d{8,}(?:[-.]\d{1,8})*\b")


def guess_reference(transaction) -> str:
    """Référence du relevé, sinon premier identifiant numérique du libellé."""
    if (transaction.reference or "").strip():
        return transaction.reference.strip()[:50]
    label = (transaction.label or "").strip()
    match = REFERENCE_RE.search(label)
    if match:
        return match.group(0)[:50]
    return label[:50]


def guess_counterpart_code(transaction) -> str:
    """Compte de contrepartie probable selon le sens, le libellé et le tiers."""
    company = transaction.company
    text = normalize_text(
        " ".join(
            part
            for part in (
                transaction.label,
                transaction.counterparty,
                transaction.reference,
            )
            if part
        )
    )

    def first_account(roots):
        for root in roots:
            account = (
                company.accounts.filter(code__startswith=root)
                .order_by("code")
                .first()
            )
            if account is not None:
                return account.code
        return ""

    if transaction.amount > 0:
        if any(word in text for word in ("client", "facture", "encaissement", "recette")):
            return first_account(("411",))
        return first_account(("411", "706", "701"))

    rules = (
        (("frais bancaires", "commission", "frais de tenue"), ("627",)),
        (("loyer", "location"), ("613",)),
        (("assurance",), ("616",)),
        (("honoraire", "avocat", "expert-comptable"), ("622",)),
        (("salaire", "paie"), ("421",)),
        (("urssaf", "cotisation"), ("431", "464")),
        (("impot", "taxe", "tva"), ("635",)),
        (
            ("carburant", "essence", "gazole", "diesel", "total", "shell", "esso"),
            ("6063", "606"),
        ),
        (("restaurant", "repas", "cafe", "hotel"), ("625", "6063")),
        (("fournisseur", "facture", "achat"), ("401", "6063")),
    )
    for words, roots in rules:
        if any(word in text for word in words):
            return first_account(roots)
    return first_account(("6063", "606", "625", "606"))
