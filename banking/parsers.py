"""Parsing des relevés CSV, OFX/QFX et PDF."""

from __future__ import annotations

import csv
import html
import io
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from documents.receipt_ocr import ReceiptOcrError, extract_receipt_text

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


# ---------------------------------------------------------------------------
# PDF : lecture des colonnes par coordonnées, puis repli texte/OCR.
# ---------------------------------------------------------------------------
_PDF_DATE_RE = re.compile(r"^\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})(?!\d)")
_PDF_AMOUNT_WORD_RE = re.compile(r"^[+-]?\d[\d\s.,]*[.,]\d{2}$")
_PDF_AMOUNT_FIND_RE = re.compile(
    r"(?<![\d/])([+-]?(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})*|\d+)[.,]\d{2})(?![\d/])"
)
_PDF_MAX_PAGES = 50


def _pdf_words(data: bytes) -> list[list[tuple[float, float, float, str]]]:
    """Mots du PDF avec leurs coordonnées, page par page.

    PyMuPDF (précis) d'abord ; sinon pdfminer.six, purement Python, qui
    donne des mots approchés — suffisant pour rejouer le layout colonnes.
    """
    try:
        import pymupdf as fitz
    except ImportError:  # anciennes installations
        try:
            import fitz
        except ImportError:
            return _pdf_words_pdfminer(data)

    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise BankParseError("PDF illisible ou corrompu.") from exc
    if getattr(document, "needs_pass", False):
        document.close()
        raise BankParseError("Ce relevé PDF est protégé par mot de passe.")
    if document.page_count > _PDF_MAX_PAGES:
        document.close()
        raise BankParseError(
            f"Relevé PDF trop long : {_PDF_MAX_PAGES} pages maximum."
        )
    pages: list[list[tuple[float, float, float, str]]] = []
    try:
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            page_words = []
            for word in page.get_text("words") or []:
                if len(word) < 5:
                    continue
                x0, y0, x1, _y1, text = word[:5]
                page_words.append((float(x0), float(y0), float(x1), str(text)))
            pages.append(page_words)
    finally:
        document.close()
    return pages


def _pdf_words_pdfminer(data: bytes) -> list[list[tuple[float, float, float, str]]]:
    """Repli sans PyMuPDF : mots approchés depuis les caractères pdfminer."""
    from io import BytesIO

    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams, LTChar, LTTextContainer, LTTextLine

    pages: list[list[tuple[float, float, float, str]]] = []
    try:
        layouts = extract_pages(
            BytesIO(data), maxpages=_PDF_MAX_PAGES, laparams=LAParams()
        )
    except Exception:
        return []  # PDF chiffré/illisible : le texte pur ou l'OCR prendra le relais.

    for layout_page in layouts:
        page_words: list[tuple[float, float, float, str]] = []

        def flush(word_chars: list[tuple[float, float, str]], y: float) -> None:
            if not word_chars:
                return
            page_words.append((
                min(x0 for x0, _x1, _s in word_chars),
                y,
                max(x1 for _x0, x1, _s in word_chars),
                "".join(symbol for _x0, _x1, symbol in word_chars),
            ))

        for element in layout_page:
            if not isinstance(element, LTTextContainer):
                continue
            for line in element:
                if not isinstance(line, LTTextLine):
                    continue
                y = float(line.y0)
                word_chars: list[tuple[float, float, str]] = []
                for char in line:
                    if not isinstance(char, LTChar):
                        continue
                    symbol = char.get_text()
                    if symbol.isspace():
                        flush(word_chars, y)
                        word_chars = []
                        continue
                    word_chars.append((float(char.x0), float(char.x1), symbol))
                flush(word_chars, y)
        pages.append(page_words)
    return pages


def _pdf_rows(
    page_words: list[tuple[float, float, float, str]],
) -> list[dict]:
    """Regroupe les mots d'une page en lignes visuelles."""
    rows: list[dict] = []
    for x0, y0, _x1, text in sorted(page_words, key=lambda item: (item[1], item[0])):
        target = None
        for row in rows:
            if abs(row["y"] - y0) <= 3.2:
                target = row
                break
        if target is None:
            target = {"y": y0, "words": []}
            rows.append(target)
        target["words"].append((x0, text))
    for row in rows:
        row["words"].sort(key=lambda item: item[0])
        row["text"] = " ".join(text for _x, text in row["words"])
    rows.sort(key=lambda row: row["y"])
    return rows


def _pdf_header(rows: list[dict]) -> tuple[int | None, dict[str, float]]:
    for index, row in enumerate(rows[:25]):
        normalized = normalize_text(row["text"])
        if "date" not in normalized:
            continue
        columns: dict[str, float] = {}
        for x, text in row["words"]:
            word = normalize_text(text)
            if word.startswith("date"):
                columns.setdefault("date", x)
            elif word.startswith(("debit", "retrait")):
                columns["debit"] = x
            elif word.startswith(("credit", "versement")):
                columns["credit"] = x
            elif word.startswith("solde"):
                columns["solde"] = x
            elif word.startswith(("montant", "valeur")):
                columns.setdefault("amount", x)
        if any(key in columns for key in ("debit", "credit", "amount", "solde")):
            return index, columns
    return None, {}


def _pdf_amount_words(row: dict) -> list[tuple[float, Decimal]]:
    """Montants de la ligne, en recollant « 1 » + « 250,00 »."""
    words = row["words"]
    merged: list[tuple[float, str]] = []
    index = 0
    while index < len(words):
        x, text = words[index]
        if (
            re.fullmatch(r"[+-]?\d{1,3}", text)
            and index + 1 < len(words)
            and re.fullmatch(r"\d{3}[.,]\d{2}", words[index + 1][1])
        ):
            merged.append((x, text + " " + words[index + 1][1]))
            index += 2
            continue
        merged.append((x, text))
        index += 1

    amounts: list[tuple[float, Decimal]] = []
    for x, text in merged:
        cleaned = re.sub(r"\s+", "", text.replace("€", ""))
        if not _PDF_AMOUNT_WORD_RE.fullmatch(cleaned):
            continue
        value = parse_decimal(text)
        if value is not None:
            amounts.append((x, value))
    return amounts


def _pdf_row_amount(
    amounts: list[tuple[float, Decimal]], columns: dict[str, float]
) -> tuple[Decimal | None, Decimal | None]:
    """Retourne (montant de l'opération, solde) selon les colonnes détectées."""
    if not amounts:
        return None, None
    debit_x = columns.get("debit")
    credit_x = columns.get("credit")
    amount_x = columns.get("amount")
    balance_x = columns.get("solde")
    operation: Decimal | None = None
    balance: Decimal | None = None

    for x, value in amounts:
        if balance_x is not None and x >= balance_x - 8:
            balance = value
            continue
        if debit_x is not None and credit_x is not None:
            if abs(x - debit_x) < abs(x - credit_x):
                operation = -abs(value)
            else:
                operation = abs(value)
            continue
        if debit_x is not None:
            operation = -abs(value)
            continue
        if credit_x is not None:
            operation = abs(value)
            continue
        if amount_x is not None and balance_x is not None:
            if x < balance_x - 8:
                operation = value
            else:
                balance = value
            continue
        if operation is None:
            operation = value
        else:
            balance = value

    return operation, balance


def _parse_pdf_layout(rows: list[dict]) -> list[ParsedTransaction]:
    header_index, columns = _pdf_header(rows)
    if header_index is None:
        return []

    dated_rows: list[tuple[dict, date]] = []
    for row in rows[header_index + 1 :]:
        date_match = _PDF_DATE_RE.match(row["text"])
        if not date_match:
            continue
        on_date = parse_date(date_match.group(1))
        if on_date is not None:
            dated_rows.append((row, on_date))
    if not dated_rows:
        return []

    # Certains relevés sont du plus récent au plus ancien : on remet dans
    # l'ordre chronologique pour que l'écart de solde donne le bon signe.
    descending = len(dated_rows) > 1 and dated_rows[0][1] > dated_rows[-1][1]
    if descending:
        dated_rows = list(reversed(dated_rows))

    previous_balance: Decimal | None = None
    if not descending:
        for row in rows[:header_index]:
            if "solde" not in normalize_text(row["text"]):
                continue
            amounts = _pdf_amount_words(row)
            if amounts:
                previous_balance = amounts[-1][1]

    transactions: list[ParsedTransaction] = []
    for row, on_date in dated_rows:
        amounts = _pdf_amount_words(row)
        if not amounts:
            continue
        operation, balance = _pdf_row_amount(amounts, columns)
        if balance is not None and previous_balance is not None:
            difference = (balance - previous_balance).quantize(Decimal("0.01"))
            if abs(difference) >= Decimal("0.01"):
                operation = difference
        if balance is not None:
            previous_balance = balance
        if operation is None or operation == 0:
            continue

        first_amount_x = min(x for x, _value in amounts)
        label_words = [
            text for x, text in row["words"] if x < first_amount_x - 2
        ]
        label = " ".join(label_words)
        label = _PDF_DATE_RE.sub("", label, count=1).strip(" -|:\t")
        label = re.sub(r"\s+", " ", label) or "Opération bancaire"
        transactions.append(
            ParsedTransaction(
                date=on_date,
                label=label[:255],
                amount=operation,
                counterparty=label[:200],
            )
        )
    if descending:
        transactions.reverse()
    return transactions


def _parse_pdf_text(text: str) -> list[ParsedTransaction]:
    """Repli pour les PDF scannés/OCR : une opération par ligne datée."""
    transactions: list[ParsedTransaction] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        date_match = _PDF_DATE_RE.match(line)
        if not date_match:
            continue
        rest = line[date_match.end() :]
        if "solde" in normalize_text(rest[:80]):
            continue
        amount_match = _PDF_AMOUNT_FIND_RE.search(rest)
        if not amount_match:
            continue
        on_date = parse_date(date_match.group(1))
        value = parse_decimal(amount_match.group(1))
        if on_date is None or value is None or value == 0:
            continue
        label = rest[: amount_match.start()].strip(" -|:\t")
        label = re.sub(r"\s+", " ", label) or "Opération bancaire"
        normalized = normalize_text(f"{label} {amount_match.group(1)}")
        if amount_match.group(1).startswith("-") or re.search(
            r"\b(debit|retrait|prelevement|frais|cheque)\b", normalized
        ):
            value = -abs(value)
        transactions.append(
            ParsedTransaction(
                date=on_date,
                label=label[:255],
                amount=value,
                counterparty=label[:200],
            )
        )
    return transactions


def parse_pdf(data: bytes) -> list[ParsedTransaction]:
    """Relevé PDF : colonnes natives, puis texte OCR si le PDF est un scan."""
    if not data[:1024].lstrip().startswith(b"%PDF"):
        raise BankParseError("Ce fichier n'est pas un PDF valide.")

    pages = _pdf_words(data)
    if pages:
        rows = [row for page in pages for row in _pdf_rows(page)]
        transactions = _parse_pdf_layout(rows)
        if transactions:
            return transactions
        transactions = _parse_pdf_text("\n".join(row["text"] for row in rows))
        if transactions:
            return transactions

    try:
        text = extract_receipt_text(
            data, filename="releve.pdf", content_type="application/pdf"
        )
    except ReceiptOcrError as exc:
        raise BankParseError(f"Lecture du PDF impossible : {exc}") from exc
    transactions = _parse_pdf_text(text)
    if not transactions:
        raise BankParseError(
            "Aucune opération reconnue dans ce PDF. Exportez le relevé en CSV "
            "ou vérifiez la qualité du scan."
        )
    return transactions


def parse_statement(data: bytes, filename: str = "") -> tuple[str, list[ParsedTransaction]]:
    lower = (filename or "").lower()
    if lower.endswith(".pdf") or data[:1024].lstrip().startswith(b"%PDF"):
        return "pdf", parse_pdf(data)
    head = _decode(data[:2048]).upper()
    if lower.endswith((".ofx", ".qfx")) or "OFXHEADER" in head or "<STMTTRN>" in head:
        return "ofx", parse_ofx(data)
    return "csv", parse_csv(data)
