"""Extraction « best effort » d'une facture depuis un PDF texte.

Aucune IA ici : des expressions régulières prudentes et un contrôle de
cohérence HT / TVA / TTC. Le résultat est TOUJOURS soumis à validation
humaine : une extraction partielle n'est donc pas bloquante, l'utilisateur
complète les champs à l'écran.
"""

from __future__ import annotations

import io
import logging
import re
import unicodedata
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from pdfminer.high_level import extract_text

from .schema import ExtractedInvoice, finalize_amounts

logger = logging.getLogger(__name__)

_AMOUNT_RE = re.compile(
    r"(\d{1,3}(?:[ \u00a0\u202f]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
)
_SIRET_RE = re.compile(r"\b\d{3}[ .\-]?\d{3}[ .\-]?\d{3}[ .\-]?\d{5}\b")
_VAT_RE = re.compile(r"\bFR[ .\-]?\d{2}[ .\-]?\d{9}\b", re.IGNORECASE)
_INVOICE_NUMBER_RE = re.compile(
    r"(?:facture|invoice)\s*(?:n[°ºo]\s*|num(?:éro)?\s*|#\s*|:\s*)?"
    r"([A-Za-z0-9][A-Za-z0-9\-_/.]{2,30})",
    re.IGNORECASE,
)

_MONTHS = {
    "janv": 1,
    "jan": 1,
    "fevr": 2,
    "fev": 2,
    "mars": 3,
    "avri": 4,
    "avr": 4,
    "mai": 5,
    "juin": 6,
    "juil": 7,
    "aout": 8,
    "sept": 9,
    "octo": 10,
    "oct": 10,
    "nove": 11,
    "nov": 11,
    "dece": 12,
    "dec": 12,
}

_GENERIC_WORDS = (
    "facture",
    "invoice",
    "devis",
    "avoir",
    "bon de",
    "siret",
    "siren",
    "tva",
    "total",
    "date",
    "page",
    "client",
    "adresse",
    "échéance",
    "echeance",
)


def _normalize(value: str) -> str:
    """Minuscules sans accents, pour comparer des libellés."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def _to_decimal(raw: str | None) -> Decimal | None:
    if not raw:
        return None
    cleaned = re.sub(r"[ \u00a0\u202f€]", "", raw).strip()
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    elif cleaned.count(".") > 1:
        cleaned = cleaned.replace(".", "")
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _find_date(text: str) -> date | None:
    today = date.today()
    candidates: list[tuple[int, date | None]] = []

    for match in re.finditer(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b", text):
        day, month, year = map(int, match.groups())
        candidates.append((match.start(), _safe_date(year, month, day)))

    for match in re.finditer(r"\b(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})\b", text):
        year, month, day = map(int, match.groups())
        candidates.append((match.start(), _safe_date(year, month, day)))

    for match in re.finditer(r"\b(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\.?\s+(\d{4})\b", text):
        day = int(match.group(1))
        month_key = _normalize(match.group(2))[:4]
        month = _MONTHS.get(month_key)
        year = int(match.group(3))
        if month:
            candidates.append((match.start(), _safe_date(year, month, day)))

    window_start = today - timedelta(days=3650)
    window_end = today + timedelta(days=31)
    candidates = [
        (position, value)
        for position, value in candidates
        if value is not None and window_start <= value <= window_end
    ]
    if not candidates:
        return None

    # Priorité aux lignes qui parlent explicitement de date / facture.
    for position, value in candidates:
        line_start = text.rfind("\n", 0, position) + 1
        line_end = text.find("\n", position)
        line = _normalize(
            text[line_start : line_end if line_end != -1 else len(text)]
        )
        if any(marker in line for marker in ("date", "facture", "emission")):
            return value
    return candidates[0][1]


def _line_amounts(line: str) -> list[Decimal]:
    values: list[Decimal] = []
    for match in _AMOUNT_RE.finditer(line):
        raw = match.group(1)
        value = _to_decimal(raw)
        if value is None:
            continue
        tail = line[match.end() : match.end() + 2]
        # « 20 % » est un taux, pas un montant.
        if "%" in tail and "." not in raw and "," not in raw:
            continue
        values.append(value)
    return values


def _extract_amounts(text: str) -> tuple[Decimal, Decimal, Decimal]:
    ht = vat = ttc = Decimal("0.00")
    ht_found = vat_found = ttc_found = False

    for line in text.splitlines():
        low = _normalize(line)
        values = _line_amounts(line)
        if not values:
            continue
        if not ttc_found and any(
            marker in low
            for marker in ("total ttc", "ttc", "net a payer", "total general", "montant total")
        ):
            ttc = values[-1]
            ttc_found = True
        if not ht_found and any(
            marker in low
            for marker in ("total ht", "hors taxe", "sous total", "base ht", "montant ht")
        ):
            # Ligne multi-colonnes « Total HT ... Total TTC ... » : premier montant.
            ht = values[0] if "ttc" in low else values[-1]
            ht_found = True
        if not vat_found and ("tva" in low or "t.v.a" in low):
            # Le taux a été écarté par _line_amounts ; reste le montant.
            vat = max(values)
            vat_found = True

    return ht, vat, ttc


def _extract_rate(text: str) -> Decimal:
    fallback: Decimal | None = None
    for line in text.splitlines():
        low = _normalize(line)
        match = re.search(r"(\d{1,2}(?:[.,]\d+)?)\s*%", line)
        if not match:
            continue
        value = _to_decimal(match.group(1))
        if value is None or not (Decimal("0") < value <= Decimal("30")):
            continue
        if "tva" in low or "t.v.a" in low:
            return value
        fallback = fallback or value
    return fallback or Decimal("0.00")


def _extract_invoice_number(text: str) -> str:
    for line in text.splitlines():
        for match in _INVOICE_NUMBER_RE.finditer(line):
            candidate = match.group(1).strip(" .-/")
            if not candidate or not re.search(r"\d", candidate):
                continue
            if _normalize(candidate) in {"facture", "invoice", "numero", "date"}:
                continue
            return candidate[:50]
    return ""


def _extract_supplier_name(text: str) -> str:
    for line in text.splitlines()[:15]:
        candidate = line.strip(" -|:•\t")
        if not (3 <= len(candidate) <= 70):
            continue
        low = _normalize(candidate)
        if any(word in low for word in _GENERIC_WORDS):
            continue
        if re.search(r"\d{4,}", candidate) or "http" in low or "@" in candidate:
            continue
        if sum(char.isalpha() for char in candidate) < 3:
            continue
        return candidate
    return ""


def _extract_customer_name(text: str) -> str:
    """Heuristique : nom qui suit « Facturé à », « Client », « Destinataire »."""
    labels = re.compile(
        r"(?:factur[ée]\s*[àa]|client|destinataire|adress[ée]\s*[àa])\s*[:\s]+(.+)",
        re.IGNORECASE,
    )
    for line in text.splitlines()[:40]:
        match = labels.search(line.strip())
        if not match:
            continue
        candidate = match.group(1).strip(" -|:•\t")
        low = _normalize(candidate)
        if not (3 <= len(candidate) <= 80):
            continue
        if any(word in low for word in _GENERIC_WORDS):
            continue
        if re.search(r"\d{4,}", candidate) or "@" in candidate:
            continue
        if sum(char.isalpha() for char in candidate) >= 3:
            return candidate
    return ""


def parse_text(text: str, source: str = "pdf") -> ExtractedInvoice | None:
    """Extrait les données d'un texte de facture (PDF natif ou OCR)."""
    if len((text or "").strip()) < 30:
        return None

    amount_ht, amount_vat, amount_ttc = _extract_amounts(text)
    siret_match = _SIRET_RE.search(text)
    vat_match = _VAT_RE.search(text)

    invoice = ExtractedInvoice(
        supplier_name=_extract_supplier_name(text),
        supplier_siret=(
            re.sub(r"\D", "", siret_match.group(0)) if siret_match else ""
        ),
        supplier_vat=(
            re.sub(r"\s+", "", vat_match.group(0)).upper() if vat_match else ""
        ),
        customer_name=_extract_customer_name(text),
        invoice_number=_extract_invoice_number(text),
        invoice_date=_find_date(text),
        amount_ht=amount_ht,
        amount_vat=amount_vat,
        amount_ttc=amount_ttc,
        vat_rate=_extract_rate(text),
        source=source,
        raw_text=text[:20000],
    )
    invoice = finalize_amounts(invoice)
    return invoice if invoice.is_usable() else None


def parse_pdf(data: bytes) -> ExtractedInvoice | None:
    """Extrait les données d'un PDF texte ; ``None`` si rien d'exploitable."""
    try:
        text = extract_text(io.BytesIO(data), maxpages=8) or ""
    except Exception:
        logger.info("PDF illisible pour l'extraction texte.", exc_info=True)
        return None
    return parse_text(text, source="pdf")
