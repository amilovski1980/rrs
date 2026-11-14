"""Point d'entrée du parsing : choisit l'extracteur selon le fichier."""

from .schema import ExtractedInvoice
from . import pdf_invoice, xml_invoice


def parse_attachment(filename: str, data: bytes) -> ExtractedInvoice | None:
    """Retourne une facture normalisée, ou ``None`` si non exploitable."""
    name = (filename or "").lower()
    if name.endswith(".xml"):
        invoice = xml_invoice.parse_xml(data)
        return invoice if invoice and invoice.is_usable() else None
    if name.endswith(".pdf"):
        # 1) PDF hybride Factur-X : le XML embarqué est la source la plus fiable.
        facturx = xml_invoice.parse_facturx_pdf(data)
        if facturx and facturx.is_usable():
            return facturx
        # 2) PDF texte classique (regex + contrôle de cohérence).
        return pdf_invoice.parse_pdf(data)
    return None


__all__ = ["ExtractedInvoice", "parse_attachment"]
