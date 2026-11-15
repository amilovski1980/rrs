"""Extraction des factures XML : UBL (OASIS) et CII (Factur-X / ZUGFeRD).

Le parseur travaille sur les noms locaux des balises : il tolère donc les
différentes versions de namespaces (UBL 2.1, CII D16B, profils Factur-X
BASIC / EN16931 / EXTENDED).
"""

from __future__ import annotations

import io
import logging
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET

from .schema import ExtractedInvoice, finalize_amounts

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Utilitaires XML (namespaces ignorés)
# ---------------------------------------------------------------------------
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _child(element, name: str):
    if element is None:
        return None
    return next((child for child in element if _local(child.tag) == name), None)


def _path(element, *names: str):
    current = element
    for name in names:
        current = _child(current, name)
        if current is None:
            return None
    return current


def _find_any(element, name: str):
    if element is None:
        return None
    return next((node for node in element.iter() if _local(node.tag) == name), None)


def _find_all(element, name: str) -> list:
    if element is None:
        return []
    return [node for node in element.iter() if _local(node.tag) == name]


def _text(element) -> str:
    return (element.text or "").strip() if element is not None else ""


def _attr(element, name: str) -> str:
    if element is None:
        return ""
    for key, value in element.attrib.items():
        if _local(key) == name:
            return value
    return ""


def _decimal(value: str | None) -> Decimal | None:
    text = (value or "").strip().replace(" ", "").replace("\u00a0", "")
    text = re.sub(r"[^\d,.\-]", "", text)
    if not text:
        return None
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    elif "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    try:
        return Decimal(text).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _looks_like_siret(value: str) -> bool:
    return len(_digits(value)) == 14


def _looks_like_vat(value: str) -> bool:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", value or "").upper()
    return len(cleaned) >= 8 and cleaned[:2].isalpha()


def _parse_date(text: str, fmt: str = "") -> date | None:
    text = (text or "").strip()
    if not text:
        return None
    if fmt == "102" and re.fullmatch(r"\d{8}", text):
        return date(int(text[0:4]), int(text[4:6]), int(text[6:8]))
    if fmt == "610" and re.fullmatch(r"\d{6}", text):
        return date(int(text[0:4]), int(text[4:6]), 1)
    for pattern in ("%Y-%m-%d", "%Y%m%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text[:10], pattern).date()
        except ValueError:
            continue
    return None


def _party_identity(party) -> tuple[str, str, str]:
    """Retourne ``(nom, siret, tva)`` d'un nœud Party UBL ou CII."""
    if party is None:
        return "", "", ""
    name = _text(_child(party, "Name"))
    if not name:
        name = _text(_find_any(party, "Name"))
    siret = vat = ""
    for node in party.iter():
        if _local(node.tag) not in {"CompanyID", "ID"}:
            continue
        value = re.sub(r"\s+", "", node.text or "")
        if not value:
            continue
        if not siret and _looks_like_siret(value):
            siret = _digits(value)
        elif not vat and _looks_like_vat(value):
            vat = value.upper()[:20]
    return name.strip(), siret, vat


def _first_description(root) -> str:
    if root is None:
        return ""
    for node in root.iter():
        if _local(node.tag) in {"Description", "Name"}:
            text = _text(node)
            if text and len(text) > 2:
                return text[:255]
    return ""


# ---------------------------------------------------------------------------
# UBL (facture électronique OASIS)
# ---------------------------------------------------------------------------
def _parse_ubl(root) -> ExtractedInvoice:
    supplier_party = _path(root, "AccountingSupplierParty", "Party")
    if supplier_party is None:
        supplier_party = _find_any(root, "SellerSupplierParty")
    supplier_name, siret, vat = _party_identity(supplier_party)
    buyer_party = _path(root, "AccountingCustomerParty", "Party")
    if buyer_party is None:
        buyer_party = _find_any(root, "BuyerCustomerParty")
    buyer_name, buyer_siret, buyer_vat = _party_identity(buyer_party)

    totals = _find_any(root, "LegalMonetaryTotal")
    amount_ht = _decimal(_text(_child(totals, "TaxExclusiveAmount")))
    amount_ttc = _decimal(_text(_child(totals, "TaxInclusiveAmount")))
    if amount_ttc is None:
        amount_ttc = _decimal(_text(_child(totals, "PayableAmount")))

    tax_total = _find_any(root, "TaxTotal")
    amount_vat = _decimal(_text(_child(tax_total, "TaxAmount")))
    rate = _decimal(_text(_path(tax_total, "TaxSubtotal", "Percent")))
    if rate is None:
        rate = _decimal(_text(_find_any(tax_total, "Percent")))

    return ExtractedInvoice(
        supplier_name=supplier_name,
        supplier_siret=siret,
        supplier_vat=vat,
        customer_name=buyer_name,
        customer_siret=buyer_siret,
        customer_vat=buyer_vat,
        invoice_number=_text(_child(root, "ID")),
        invoice_date=_parse_date(_text(_child(root, "IssueDate"))),
        amount_ht=amount_ht or Decimal("0.00"),
        amount_vat=amount_vat or Decimal("0.00"),
        amount_ttc=amount_ttc or Decimal("0.00"),
        vat_rate=rate or Decimal("0.00"),
        currency=_text(_child(root, "DocumentCurrencyCode")) or "EUR",
        description=_first_description(_child(root, "InvoiceLine")),
        source="ubl",
    )


# ---------------------------------------------------------------------------
# CII (Factur-X / ZUGFeRD)
# ---------------------------------------------------------------------------
def _parse_cii(root) -> ExtractedInvoice:
    document = _find_any(root, "ExchangedDocument")
    invoice_number = _text(_child(document, "ID"))
    if not invoice_number:
        invoice_number = _text(_find_any(root, "InvoiceNumber"))

    invoice_date = None
    issue = _child(document, "IssueDateTime")
    date_string = _child(issue, "DateTimeString")
    if date_string is not None:
        invoice_date = _parse_date(_text(date_string), _attr(date_string, "format"))
    if invoice_date is None:
        fallback = _find_any(root, "DateTimeString")
        if fallback is not None:
            invoice_date = _parse_date(_text(fallback), _attr(fallback, "format"))

    supplier_party = _find_any(root, "SellerTradeParty")
    supplier_name, siret, vat = _party_identity(supplier_party)
    buyer_party = _find_any(root, "BuyerTradeParty")
    buyer_name, buyer_siret, buyer_vat = _party_identity(buyer_party)

    settlement = _find_any(root, "SpecifiedTradeSettlementHeaderMonetarySummation")
    amount_ht = _decimal(_text(_child(settlement, "LineTotalAmount")))
    amount_ttc = _decimal(_text(_child(settlement, "GrandTotalAmount")))
    if amount_ttc is None:
        amount_ttc = _decimal(_text(_child(settlement, "DuePayableAmount")))

    amount_vat = None
    tax_nodes = _find_all(settlement, "TaxTotalAmount")
    for node in tax_nodes:
        currency = _attr(node, "currencyID").upper()
        if currency in ("", "EUR"):
            amount_vat = _decimal(_text(node))
            break
    if amount_vat is None and tax_nodes:
        amount_vat = _decimal(_text(tax_nodes[0]))

    rate = None
    trade_tax = _find_any(settlement, "ApplicableTradeTax")
    if trade_tax is not None:
        rate = _decimal(_text(_child(trade_tax, "RateApplicablePercent")))

    product = _find_any(root, "SpecifiedTradeProduct")
    description = _text(_child(product, "Name"))

    return ExtractedInvoice(
        supplier_name=supplier_name,
        supplier_siret=siret,
        supplier_vat=vat,
        customer_name=buyer_name,
        customer_siret=buyer_siret,
        customer_vat=buyer_vat,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        amount_ht=amount_ht or Decimal("0.00"),
        amount_vat=amount_vat or Decimal("0.00"),
        amount_ttc=amount_ttc or Decimal("0.00"),
        vat_rate=rate or Decimal("0.00"),
        description=description[:255],
        source="cii",
    )


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------
def parse_xml(data: bytes) -> ExtractedInvoice | None:
    """Parse un XML UBL ou CII ; ``None`` si le document n'est pas reconnu."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        logger.info("XML de facture illisible.")
        return None

    local_name = _local(root.tag)
    try:
        if local_name == "Invoice":
            return finalize_amounts(_parse_ubl(root))
        if local_name == "CrossIndustryInvoice":
            return finalize_amounts(_parse_cii(root))
    except Exception:
        logger.exception("Parsing XML de facture en échec.")
    return None


def parse_facturx_pdf(data: bytes) -> ExtractedInvoice | None:
    """Extrait le XML embarqué d'un PDF hybride Factur-X / ZUGFeRD."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        attachments = getattr(reader, "attachments", None) or {}
    except Exception:
        logger.info("PDF hybride : pièces jointes illisibles.")
        return None

    candidates: list[tuple[int, bytes]] = []
    for name, blobs in attachments.items():
        lowered = (name or "").lower()
        if not lowered.endswith(".xml") or not blobs:
            continue
        priority = 0 if any(
            marker in lowered for marker in ("factur-x", "facturx", "zugferd", "cii")
        ) else 1
        candidates.append((priority, blobs[0]))

    for _, blob in sorted(candidates, key=lambda item: item[0]):
        invoice = parse_xml(blob)
        if invoice and invoice.is_usable():
            invoice.source = "facturx"
            return invoice
    return None
