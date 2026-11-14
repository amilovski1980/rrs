"""Modèle de données commun aux parseurs de factures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass
class ExtractedInvoice:
    """Résultat normalisé d'un XML Factur-X/UBL ou d'un PDF texte.

    Les montants valent ``0.00`` quand l'extraction n'a rien trouvé : l'écran
    de validation affiche toujours des champs éditables, jamais une erreur
    bloquante pour un PDF mal structuré.
    """

    supplier_name: str = ""
    supplier_siret: str = ""
    supplier_vat: str = ""
    invoice_number: str = ""
    invoice_date: date | None = None
    amount_ht: Decimal = Decimal("0.00")
    amount_vat: Decimal = Decimal("0.00")
    amount_ttc: Decimal = Decimal("0.00")
    vat_rate: Decimal = Decimal("0.00")
    currency: str = "EUR"
    description: str = ""
    source: str = "pdf"
    raw_text: str = ""

    def is_usable(self) -> bool:
        return bool(
            self.invoice_number
            or self.amount_ttc > 0
            or self.amount_ht > 0
        )


def finalize_amounts(invoice: ExtractedInvoice) -> ExtractedInvoice:
    """Complète les montants manquants (HT / TVA / TTC) et le taux."""
    step = Decimal("0.01")
    ht, vat, ttc = invoice.amount_ht, invoice.amount_vat, invoice.amount_ttc

    if ht <= 0 and ttc > 0:
        ht = (ttc - vat).quantize(step)
    if ttc <= 0 and ht > 0:
        ttc = (ht + vat).quantize(step)
    if vat <= 0 and ht > 0 and ttc > ht:
        vat = (ttc - ht).quantize(step)
    if invoice.vat_rate <= 0 and ht > 0 and vat > 0:
        invoice.vat_rate = (vat / ht * Decimal("100")).quantize(step)

    invoice.amount_ht = max(ht, Decimal("0.00")).quantize(step)
    invoice.amount_vat = max(vat, Decimal("0.00")).quantize(step)
    invoice.amount_ttc = max(ttc, Decimal("0.00")).quantize(step)
    return invoice
