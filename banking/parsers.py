"""Parsing des relevés CSV et OFX/QFX."""

from __future__ import annotations

import csv
import html
import io
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .utils import normalize_text, parse_date, parse_decimal


class BankParseError(Exception):
    """Le fichier ne peut pas être interprété comme un relevé."""


@dataclass
class ParsedTransaction:
    date: date
    label: str
    amount: Decimal
    counterparty: str = ""
    reference: str = ""
    external_id: str = ""


_HEADER_ALIASES = {
    "date": (
        "date",
        "dateoperation",
        "datevaleur",
        "dateop",
        "operationdate",
    ),
    "label": (
        "libelle",
        "libelleoperation",
        "description",
        "nature",
        "natureoperation",
        "operation",
        "operations",
        "details",
        "detail",
        "intitule",
    ),
    "debit": ("debit", "debits", "montantdebit"),
    "credit": ("credit", "credits", "montantcredit"),
    "amount": ("montant", "amount", "valeur", "montantoperation", "somme"),
    "reference": (
        "reference",
        "ref",
        "numero",
        "num",
        "numeropie",
        "pieceref",
        "checknum",
    ),
    "counterparty": (
        "tiers",
        "contrepartie",
        "beneficiaire",
        "emetteur",
        "payeur",
        "donneurordre",
        "nom",
    ),
}


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", normalize_text(value))


def _guess_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:10])
    candidates = {";": sample.count(";"), ",": sample.count(","), "\t": sample.count("\t")}
    return max(candidates, key=candidates.get) if any(candidates.values()) else ";"


def _detect_columns(header) -> dict[str, int] | None:
    normalized = [_normalize_header(cell) for cell in header]
    mapping: dict[str, int] = {}
    for field, aliases in _HEADER_ALIASES.items():
        for index, cell in enumerate(normalized):
            if cell in aliases or any(cell.startswith(alias) for alias in aliases):
                mapping[field] = index
                break
    if "date" not in mapping:
        return None
    if "amount" not in mapping and "debit" not in mapping and "credit" not in mapping:
        return None
    return mapping


def _cell(row, mapping, field) -> str:
    index = mapping.get(field)
    if index is None or index >= len(row):
        return ""
    return (row[index] or "").strip()


def parse_csv(data: bytes) -> list[ParsedTransaction]:
    text = _decode(data)
    if not text.strip():
        raise BankParseError("Fichier vide.")
    delimiter = _guess_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    mapping = None
    header_index = 0
    for index, row in enumerate(rows[:15]):
        mapping = _detect_columns(row)
        if mapping:
            header_index = index
            break
    if mapping is None:
        raise BankParseError(
            "En-têtes CSV non reconnus. Colonnes attendues : date, libellé, "
            "débit/crédit ou montant, référence."
        )

    transactions: list[ParsedTransaction] = []
    for row in rows[header_index + 1 :]:
        if not any((cell or "").strip() for cell in row):
            continue
        on_date = parse_date(_cell(row, mapping, "date"))
        if on_date is None:
            continue

        debit = parse_decimal(_cell(row, mapping, "debit"))
        credit = parse_decimal(_cell(row, mapping, "credit"))
        if debit is not None and debit != 0:
            amount = -abs(debit)
        elif credit is not None and credit != 0:
            amount = abs(credit)
        else:
            amount = parse_decimal(_cell(row, mapping, "amount"))
        if amount is None or amount == 0:
            continue

        label = _cell(row, mapping, "label")
        counterparty = _cell(row, mapping, "counterparty")
        reference = _cell(row, mapping, "reference")
        transactions.append(
            ParsedTransaction(
                date=on_date,
                label=(label or counterparty or "Opération bancaire")[:255],
                amount=amount,
                counterparty=counterparty[:200],
                reference=reference[:120],
                external_id=reference[:120],
            )
        )

    if not transactions:
        raise BankParseError("Aucune opération valide trouvée dans le CSV.")
    return transactions


def _ofx_field(block: str, tag: str) -> str:
    match = re.search(rf"<{tag}>([^<\r\n]+)", block, re.IGNORECASE)
    return html.unescape(match.group(1).strip()) if match else ""


def parse_ofx(data: bytes) -> list[ParsedTransaction]:
    text = _decode(data)
    blocks = re.findall(r"<STMTTRN>(.*?)</STMTTRN>", text, re.IGNORECASE | re.DOTALL)
    if not blocks:
        # OFX 1.x tolère l'absence de balise fermante : on découpe autrement.
        blocks = re.split(r"<STMTTRN>", text, flags=re.IGNORECASE)[1:]
        blocks = [block.split("</BANKTRANLIST>")[0] for block in blocks]
    transactions: list[ParsedTransaction] = []
    for block in blocks:
        raw_date = re.sub(r"\D", "", _ofx_field(block, "DTPOSTED"))[:8]
        on_date = parse_date(raw_date)
        amount = parse_decimal(_ofx_field(block, "TRNAMT"))
        if on_date is None or amount is None or amount == 0:
            continue
        name = _ofx_field(block, "NAME")
        memo = _ofx_field(block, "MEMO")
        fit_id = _ofx_field(block, "FITID")
        check_num = _ofx_field(block, "CHECKNUM")
        label = name or memo or "Opération bancaire"
        transactions.append(
            ParsedTransaction(
                date=on_date,
                label=label[:255],
                amount=amount,
                counterparty=name[:200],
                reference=(memo or check_num)[:120],
                external_id=(fit_id or check_num)[:120],
            )
        )
    if not transactions:
        raise BankParseError("Aucune opération OFX valide trouvée.")
    return transactions


def parse_statement(data: bytes, filename: str = "") -> tuple[str, list[ParsedTransaction]]:
    lower = (filename or "").lower()
    head = _decode(data[:2048]).upper()
    if lower.endswith((".ofx", ".qfx")) or "OFXHEADER" in head or "<STMTTRN>" in head:
        return "ofx", parse_ofx(data)
    return "csv", parse_csv(data)
