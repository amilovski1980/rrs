"""PDF facture / devis / avoir, multi-pages, thèmes société.

La mise en page reprend les marges, le tableau et le pied des feuilles HTML :
en-tête, client, lignes alignées, totaux, mentions légales, numéro de page.
"""
from __future__ import annotations

from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.utils import timezone
from fpdf import FPDF

FONT = Path(__file__).resolve().parent / "fonts" / "DejaVuSans.ttf"

ACCENTS = {
    "azur": (11, 61, 145),
    "carmin": (180, 35, 24),
    "encre": (22, 22, 22),
    "sauge": (31, 122, 77),
    "graphite": (45, 52, 64),
    "indigo": (79, 70, 229),
    "terra": (180, 83, 49),
}

KIND_TITLES = {
    "invoice": "FACTURE",
    "quote": "DEVIS",
    "credit_note": "AVOIR",
}

INK = (28, 32, 38)
MUTED = (90, 98, 110)
LINE = (226, 230, 236)
ZEBRA = (246, 248, 251)


def euros(value) -> str:
    value = Decimal(str(value or 0)).quantize(Decimal("0.01"))
    whole, cents = f"{value:.2f}".split(".")
    grouped = f"{int(whole):,}".replace(",", " ")
    return f"{grouped},{cents} €"


def _qty(value) -> str:
    q = Decimal(str(value)).normalize()
    text = format(q, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _siret(company) -> str:
    data = company.source_data if isinstance(getattr(company, "source_data", None), dict) else {}
    digits = "".join(ch for ch in str(data.get("siret") or "") if ch.isdigit())
    return digits if len(digits) == 14 else ""


def _wrap(pdf: FPDF, text: str, width: float) -> list[str]:
    words = (text or "").replace("\n", " ").split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else f"{current} {word}"
        if pdf.get_string_width(trial) <= width:
            current = trial
            continue
        if current:
            lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines[:8]


class DocumentPDF(FPDF):
    def __init__(self, accent, kind_title, left, columns):
        super().__init__(format="A4", unit="mm")
        self.accent = accent
        self.kind_title = kind_title
        self.left = left
        self.columns = columns
        self.set_auto_page_break(auto=True, margin=18)

    def header(self):
        if self.page_no() <= 1:
            return
        self.set_font("DejaVu", size=8)
        self.set_text_color(*self.accent)
        self.set_xy(self.left, 10)
        self.cell(0, 5, f"{self.kind_title} — suite")
        self._table_header(16)

    def footer(self):
        self.set_y(-12)
        self.set_draw_color(*LINE)
        self.set_line_width(0.2)
        self.line(self.left, self.get_y(), 210 - 14, self.get_y())
        self.set_y(-10)
        self.set_font("DejaVu", size=8)
        self.set_text_color(*MUTED)
        self.cell(0, 4, f"Page {self.page_no()}/{{nb}}", align="C")

    def _table_header(self, y: float):
        self.set_fill_color(*self.accent)
        self.set_text_color(255, 255, 255)
        self.set_font("DejaVu", size=8)
        x = self.left
        for width, label, align in self.columns:
            self.set_xy(x, y)
            pad = "  " if align == "L" else ""
            self.cell(width, 7, pad + label, align=align, fill=True)
            x += width
        self.set_text_color(*INK)
        self.set_y(y + 7)


def _columns(width: float):
    parts = (
        (0.40, "Désignation", "L"),
        (0.10, "Qté", "R"),
        (0.14, "PU HT", "R"),
        (0.10, "TVA", "R"),
        (0.13, "HT", "R"),
        (0.13, "TTC", "R"),
    )
    raw = [round(width * share, 2) for share, _label, _align in parts]
    raw[-1] = round(width - sum(raw[:-1]), 2)
    return [(raw[i], parts[i][1], parts[i][2]) for i in range(len(parts))]


def _draw_chrome(pdf: DocumentPDF, theme: str, accent):
    if theme == "azur":
        pdf.set_fill_color(*accent)
        pdf.rect(0, 0, 210, 48, "F")
    elif theme == "carmin":
        pdf.set_fill_color(*accent)
        pdf.rect(0, 0, 8, 297, "F")
    elif theme == "sauge":
        pdf.set_fill_color(244, 250, 246)
        pdf.rect(0, 0, 210, 297, "F")
    elif theme == "graphite":
        pdf.set_fill_color(28, 32, 38)
        pdf.rect(0, 0, 210, 50, "F")
        pdf.set_fill_color(*accent)
        pdf.rect(0, 50, 210, 1.6, "F")
    elif theme == "indigo":
        pdf.set_fill_color(*accent)
        pdf.rect(0, 0, 210, 4, "F")
    elif theme == "terra":
        pdf.set_fill_color(246, 235, 227)
        pdf.rect(0, 0, 22, 297, "F")
        pdf.set_fill_color(*accent)
        pdf.rect(0, 0, 6, 297, "F")
    else:
        pdf.set_draw_color(*accent)
        pdf.set_line_width(0.6)
        pdf.line(pdf.left, 46, 196, 46)


def _header_ink(theme: str):
    if theme in ("azur", "graphite"):
        return (255, 255, 255)
    return INK


def _meta_muted(theme: str):
    if theme == "azur":
        return (214, 228, 255)
    if theme == "graphite":
        return (186, 194, 204)
    return MUTED


def _line_items(document):
    """Normalise les lignes (facture/devis) ou fabrique une ligne héritée."""
    lines = list(getattr(document, "lines", None).all()) if hasattr(document, "lines") else []
    if lines:
        rows = []
        for line in lines:
            rows.append(
                {
                    "description": line.description,
                    "quantity": line.quantity,
                    "unit_price": line.unit_price,
                    "vat_rate": line.vat_rate,
                    "amount_ht": line.amount_ht,
                    "amount_ttc": getattr(line, "amount_ttc", None)
                    or (line.amount_ht * (Decimal("1") + line.vat_rate / Decimal("100"))).quantize(
                        Decimal("0.01")
                    ),
                }
            )
        return rows
    client_name, _ = _client_fields(document)
    label = "Avoir" if hasattr(document, "invoice") and not hasattr(document, "client_name") else "Prestation"
    return [
        {
            "description": f"{label} — {client_name}",
            "quantity": Decimal("1"),
            "unit_price": document.amount_ht,
            "vat_rate": document.vat_rate,
            "amount_ht": document.amount_ht,
            "amount_ttc": document.amount_ttc,
        }
    ]


def _client_fields(document):
    name = getattr(document, "client_name", None)
    if not name and hasattr(document, "invoice"):
        name = document.invoice.client_name
    siren = getattr(document, "client_siren", "") or ""
    if not siren and hasattr(document, "invoice"):
        siren = document.invoice.client_siren
    return name or "Client", siren


def _vat_lines(rows):
    buckets: dict[Decimal, Decimal] = {}
    for row in rows:
        rate = Decimal(str(row["vat_rate"])).quantize(Decimal("0.01"))
        vat = (Decimal(str(row["amount_ttc"])) - Decimal(str(row["amount_ht"]))).quantize(Decimal("0.01"))
        buckets[rate] = buckets.get(rate, Decimal("0.00")) + vat
    return sorted(buckets.items(), key=lambda item: item[0])


def render_document_pdf(document, company, kind: str = "invoice") -> bytes:
    theme = company.invoice_theme if company.invoice_theme in ACCENTS else "azur"
    accent = ACCENTS[theme]
    kind_title = KIND_TITLES.get(kind, "FACTURE")
    client_name, client_siren = _client_fields(document)
    rows = _line_items(document)
    left = 32 if theme == "terra" else 16
    right = 14
    content_w = 210 - left - right
    columns = _columns(content_w)

    pdf = DocumentPDF(accent, kind_title, left, columns)
    pdf.alias_nb_pages()
    pdf.add_font("DejaVu", "", str(FONT))
    pdf.set_font("DejaVu", size=10)
    pdf.add_page()
    _draw_chrome(pdf, theme, accent)

    ink = _header_ink(theme)
    x = left
    if company.logo:
        try:
            pdf.image(BytesIO(bytes(company.logo)), x=x, y=12, h=14)
            x += 18
        except Exception:
            x = left

    pdf.set_text_color(*ink)
    pdf.set_xy(x, 12)
    pdf.set_font_size(14)
    name_w = 92 if x == left else 76
    pdf.multi_cell(name_w, 6, (company.denomination or "")[:80])
    pdf.set_font_size(8.5)
    info = []
    if company.address:
        info.append(company.address[:110])
    identity = f"{company.forme} · SIREN {company.siren}"
    siret = _siret(company)
    if siret:
        identity += f" · SIRET {siret}"
    info.append(identity)
    if company.phone:
        info.append(company.phone)
    if company.email:
        info.append(company.email)
    pdf.set_xy(x, 26)
    pdf.multi_cell(name_w, 4, "\n".join(info))

    meta_w = 62
    meta_x = 210 - right - meta_w
    pdf.set_text_color(*(accent if theme not in ("azur", "graphite") else ink))
    pdf.set_xy(meta_x, 12)
    pdf.set_font_size(16)
    pdf.cell(meta_w, 8, kind_title, align="R")
    pdf.set_text_color(*_meta_muted(theme))
    pdf.set_font_size(10)
    pdf.set_xy(meta_x, 22)
    pdf.cell(meta_w, 5, str(document.number or ""), align="R")
    when = timezone.localtime(document.created_at).strftime("%d/%m/%Y")
    pdf.set_xy(meta_x, 28)
    pdf.cell(meta_w, 5, when, align="R")
    status = document.get_status_display() if hasattr(document, "get_status_display") else ""
    if status:
        pdf.set_xy(meta_x, 34)
        pdf.cell(meta_w, 5, status, align="R")

    y_client = 56
    pdf.set_text_color(*accent)
    pdf.set_xy(left, y_client)
    pdf.set_font_size(8)
    label = "FACTURÉ À" if kind == "invoice" else ("DESTINATAIRE" if kind == "quote" else "CLIENT")
    pdf.cell(content_w, 4, label)
    pdf.set_text_color(*INK)
    pdf.set_xy(left, y_client + 6)
    pdf.set_font_size(12)
    pdf.cell(content_w, 6, (client_name or "Client")[:90])
    pdf.set_font_size(9)
    pdf.set_text_color(*MUTED)
    pdf.set_xy(left, y_client + 13)
    client_line = f"SIREN {client_siren}" if client_siren else "Client"
    pdf.cell(content_w, 5, client_line)

    table_y = y_client + 22
    pdf._table_header(table_y)
    pdf.set_font("DejaVu", size=9)

    desc_w = columns[0][0]
    fill = False
    for row in rows:
        chunks = _wrap(pdf, row["description"] or "", desc_w - 4)
        row_h = max(8, 4.3 * len(chunks) + 2.4)
        if pdf.get_y() + row_h > 262:
            pdf.add_page()
        y = pdf.get_y()
        pdf.set_fill_color(*(ZEBRA if fill else (255, 255, 255)))
        pdf.rect(left, y, content_w, row_h, style="F")
        pdf.set_draw_color(*LINE)
        pdf.set_line_width(0.15)
        pdf.line(left, y + row_h, left + content_w, y + row_h)
        pdf.set_text_color(*INK)
        for index, chunk in enumerate(chunks):
            pdf.set_xy(left + 2, y + 1.2 + index * 4.3)
            pdf.cell(desc_w - 4, 4.3, chunk)
        cursor = left + desc_w
        values = (
            _qty(row["quantity"]),
            euros(row["unit_price"]),
            f"{Decimal(str(row['vat_rate'])):.2f} %",
            euros(row["amount_ht"]),
            euros(row["amount_ttc"]),
        )
        for (width, _label, align), value in zip(columns[1:], values):
            pdf.set_xy(cursor, y)
            pdf.cell(width - 1.5, row_h, value, align=align)
            cursor += width
        pdf.set_y(y + row_h)
        fill = not fill

    if pdf.get_y() > 230:
        pdf.add_page()

    box_w = min(86, content_w)
    box_x = left + content_w - box_w
    y = pdf.get_y() + 6
    pdf.set_text_color(*INK)
    pdf.set_font_size(10)
    pdf.set_xy(box_x, y)
    pdf.cell(box_w * 0.52, 6, "Total HT")
    pdf.cell(box_w * 0.48, 6, euros(document.amount_ht), align="R")
    y += 6
    for rate, amount in _vat_lines(rows):
        pdf.set_xy(box_x, y)
        pdf.cell(box_w * 0.52, 6, f"TVA {rate:.2f} %")
        pdf.cell(box_w * 0.48, 6, euros(amount), align="R")
        y += 6
    pdf.set_fill_color(*accent)
    pdf.set_text_color(255, 255, 255)
    pdf.set_xy(box_x, y + 1)
    pdf.set_font_size(11)
    pdf.cell(box_w * 0.52, 8, "  Total TTC", fill=True)
    pdf.set_font_size(12)
    pdf.cell(box_w * 0.48, 8, euros(document.amount_ttc) + "  ", align="R", fill=True)

    notes = {
        "invoice": "Payable à réception.",
        "quote": "Devis valable selon les conditions convenues.",
        "credit_note": "Avoir à déduire de la facture d'origine.",
    }
    legal = [
        f"{company.forme} — SIREN {company.siren}" + (f" — SIRET {siret}" if siret else ""),
        f"Date : {when}.",
        notes.get(kind, ""),
    ]
    if getattr(company, "tva", "") == "franchise" and Decimal(str(document.vat_amount or 0)) == 0:
        legal.append("TVA non applicable, article 293 B du CGI.")
    if kind == "invoice":
        legal.append(
            "En cas de retard de paiement : pénalités de trois fois le taux d'intérêt légal "
            "et indemnité forfaitaire de recouvrement de 40 € (art. L441-10 du code de commerce)."
        )
    pdf.set_text_color(*MUTED)
    pdf.set_font_size(8)
    pdf.set_xy(left, y + 14)
    pdf.multi_cell(content_w, 3.8, "\n".join(part for part in legal if part))

    return bytes(pdf.output())


def render_invoice_pdf(invoice, company) -> bytes:
    return render_document_pdf(invoice, company, kind="invoice")


def render_quote_pdf(quote, company) -> bytes:
    return render_document_pdf(quote, company, kind="quote")


def render_credit_note_pdf(credit_note, company) -> bytes:
    return render_document_pdf(credit_note, company, kind="credit_note")
