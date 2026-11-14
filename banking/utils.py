"""Normalisation des relevés bancaires (montants, dates, libellés)."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


def normalize_text(value: str) -> str:
    """Minuscules, sans accents, espaces compactés."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    cleaned = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def parse_decimal(value: str | None) -> Decimal | None:
    """Montant français ou international, signe conservé."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()").replace("\u00a0", "").replace("\u202f", "")
    text = re.sub(r"[^\d,.\-+]", "", text)
    if not text:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    try:
        amount = Decimal(text).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    if negative and amount > 0:
        amount = -amount
    return amount


def parse_date(value: str | None) -> date | None:
    """Dates bancaires usuelles : JJ/MM/AAAA, AAAA-MM-JJ, AAAAMMJJ..."""
    text = (value or "").strip()
    if not text:
        return None
    text = text.split("T")[0].split(" ")[0]
    for pattern in (
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y%m%d",
        "%d/%m/%y",
        "%d-%m-%y",
    ):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def make_fingerprint(
    account_id, on_date: date, amount: Decimal, label: str, external_id: str = ""
) -> str:
    """Empreinte stable d'une opération, pour éviter les doublons d'import."""
    raw = "|".join(
        [
            str(account_id),
            on_date.isoformat() if on_date else "",
            str(amount),
            normalize_text(label),
            normalize_text(external_id),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
