"""PDF facture / devis / avoir, multi-pages, thèmes société."""
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


def euros(value) -> str:
    value = Decimal(str(value)).quantize(Decimal("0.01"))
    whole, cents = f"{value:.2f}".split(".")
    grouped = f"{int(whole):,}".replace(",", " ")
    return f"{grouped},{cents} €"


def _qty(value) -> str:
    q = Decimal(str(value)).normalize()
    text = format(q, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


class DocumentPDF(FPDF):
    def __init__(self, theme: str, accent: tuple[int, int, int], kind_title: str):
        super().__init__(format="A4", unit="mm")
        self.theme = theme
        self.accent = accent
        self.kind_title = kind_title
        self.set_auto_page_break(auto=True, margin=22)

    def header(self):
        # En-tête de continuation après saut de page (lignes uniquement).
        if self.page_no() <= 1:
            return
        self.set_font("DejaVu", size=9)
        self.set_text_color(*self.accent)
        self.set_xy(16, 12)
        self.cell(0, 5, f"{self.kind_title} (suite)")
        self.set_draw_color(*self.accent)
        self.set_line_width(0.3)
        self.line(16, 18, 194, 18)
        self.set_xy(16, 22)
        self._draw_table_header(y=22)

    def footer(self):
        self.set_y(-14)
        self.set_font("DejaVu", size=8)
        self.set_text_color(110, 116, 128)
        self.cell(0, 4, f"Page {self.page_no()}/{{nb}}", align="C")

    def _draw_table_header(self, y: float):
        self.set_fill_color(*self.accent)
        self.set_text_color(255, 255, 255)
        self.set_font("DejaVu", size=8)
        self.set_xy(16, y)
        self.cell(70, 7, "  Désignation", fill=True)
        self.cell(18, 7, "Qté", align="R", fill=True)
        self.cell(28, 7, "PU HT", align="R", fill=True)
        self.cell(18, 7, "TVA", align="R", fill=True)
        self.cell(28, 7, "HT", align="R", fill=True)
        self.cell(26, 7, "TTC  ", align="R", fill=True)
        self.set_text_color(28, 32, 38)
        self.set_y(y + 8)


def _draw_chrome(pdf: DocumentPDF, company, theme: str, accent):
    if theme == "azur":
        pdf.set_fill_color(*accent)
        pdf.rect(0, 0, 210, 46, "F")
    elif theme == "carmin":
        pdf.set_fill_color(*accent)
        pdf.rect(0, 0, 7, 297, "F")
    elif theme == "sauge":
        pdf.set_fill_color(244, 250, 246)
        pdf.rect(0, 0, 210, 297, "F")
    elif theme == "graphite":
        pdf.set_fill_color(28, 32, 38)
        pdf.rect(0, 0, 210, 50, "F")
        pdf.set_fill_color(*accent)
        pdf.rect(0, 50, 210, 2, "F")
    elif theme == "indigo":
        pdf.set_draw_color(*accent)
        pdf.set_line_width(1.2)
        pdf.line(16, 14, 16, 42)
        pdf.set_line_width(0.4)
        pdf.line(16, 48, 194, 48)
    elif theme == "terra":
        pdf.set_fill_color(245, 236, 226)
        pdf.rect(0, 0, 28, 297, "F")
        pdf.set_fill_color(*accent)
        pdf.rect(0, 0, 6, 297, "F")
    else:  # encre
        pdf.set_draw_color(*accent)
        pdf.set_line_width(0.6)
        pdf.line(16, 44, 194, 44)


def _header_ink(theme: str) -> tuple[int, int, int]:
    if theme in ("azur", "graphite"):
        return (255, 255, 255)
    return (28, 32, 38)


def _meta_muted(theme: str) -> tuple[int, int, int]:
    if theme == "azur":
        return (214, 228, 255)
    if theme == "graphite":
        return (180, 188, 200)
    return (40, 44, 52)


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


def render_document_pdf(document, company, kind: str = "invoice") -> bytes:
    theme = company.invoice_theme if company.invoice_theme in ACCENTS else "azur"
    accent = ACCENTS[theme]
    kind_title = KIND_TITLES.get(kind, "FACTURE")
    client_name, client_siren = _client_fields(document)
    rows = _line_items(document)

    pdf = DocumentPDF(theme, accent, kind_title)
    pdf.alias_nb_pages()
    pdf.add_font("DejaVu", "", str(FONT))
    pdf.set_font("DejaVu", size=11)
    pdf.add_page()

    _draw_chrome(pdf, company, theme, accent)

    left = 18 if theme in ("carmin", "terra") else 16
    if theme == "terra":
        left = 34
    ink = _header_ink(theme)

    x = left
    if company.logo:
        try:
            pdf.image(BytesIO(bytes(company.logo)), x=x, y=12, h=16)
            x += 22
        except Exception:
            pass

    pdf.set_text_color(*ink)
    pdf.set_xy(x, 12)
    pdf.set_font_size(15)
    pdf.cell(95, 7, (company.denomination or "")[:48])
    pdf.set_font_size(9)
    info = []
    if company.address:
        info.append(company.address)
    info.append(f"{company.forme} · SIREN {company.siren}")
    if company.phone:
        info.append(company.phone)
    if company.email:
        info.append(company.email)
    pdf.set_xy(x, 20)
    pdf.multi_cell(95, 4.2, "\n".join(info))

    meta_x = 120
    pdf.set_text_color(*(accent if theme not in ("azur", "graphite") else ink))
    pdf.set_xy(meta_x, 12)
    pdf.set_font_size(16)
    pdf.cell(74, 8, kind_title, align="R")
    pdf.set_text_color(*_meta_muted(theme))
    pdf.set_font_size(10)
    pdf.set_xy(meta_x, 22)
    pdf.cell(74, 5, document.number, align="R")
    when = timezone.localtime(document.created_at).strftime("%d/%m/%Y")
    pdf.set_xy(meta_x, 28)
    pdf.cell(74, 5, when, align="R")
    status = document.get_status_display() if hasattr(document, "get_status_display") else ""
    pdf.set_xy(meta_x, 34)
    pdf.cell(74, 5, status, align="R")

    # Client
    y_client = 58 if theme != "graphite" else 60
    pdf.set_text_color(*accent)
    pdf.set_xy(left, y_client)
    pdf.set_font_size(8)
    label = "FACTURÉ À" if kind == "invoice" else ("DESTINATAIRE" if kind == "quote" else "CLIENT")
    pdf.cell(0, 4, label)
    pdf.set_text_color(28, 32, 38)
    pdf.set_xy(left, y_client + 6)
    pdf.set_font_size(13)
    pdf.cell(0, 6, client_name[:80])
    pdf.set_font_size(9)
    pdf.set_xy(left, y_client + 13)
    pdf.cell(0, 5, f"SIREN {client_siren}" if client_siren else "Client")

    # Table header
    table_y = y_client + 26
    pdf._draw_table_header(y=table_y)

    # Rows
    fill = False
    for row in rows:
        desc = (row["description"] or "").strip()
        # Découpe en 1–3 lignes de ~36 car. pour la colonne désignation.
        chunks = []
        rest = desc
        while rest and len(chunks) < 3:
            if len(rest) <= 36:
                chunks.append(rest)
                rest = ""
            else:
                cut = rest[:36]
                sp = cut.rfind(" ")
                if sp >= 18:
                    chunks.append(rest[:sp])
                    rest = rest[sp + 1 :]
                else:
                    chunks.append(cut)
                    rest = rest[36:]
        if rest:
            chunks[-1] = chunks[-1][:33] + "…"
        row_h = max(9, 5 + 4.2 * len(chunks))
        if pdf.get_y() + row_h > 265:
            pdf.add_page()
        if fill:
            pdf.set_fill_color(248, 249, 251)
        else:
            pdf.set_fill_color(255, 255, 255)
        y = pdf.get_y()
        pdf.set_xy(16, y)
        pdf.set_font("DejaVu", size=9)
        pdf.set_text_color(28, 32, 38)
        # Fond de ligne
        pdf.rect(16, y, 188, row_h, style="F")
        pdf.set_xy(18, y + 2)
        for i, chunk in enumerate(chunks):
            pdf.set_xy(18, y + 2 + i * 4.2)
            pdf.cell(66, 4.2, chunk)
        pdf.set_xy(86, y)
        pdf.cell(18, row_h, _qty(row["quantity"]), align="R")
        pdf.cell(28, row_h, euros(row["unit_price"]), align="R")
        pdf.cell(18, row_h, f"{Decimal(row['vat_rate']):.2f} %", align="R")
        pdf.cell(28, row_h, euros(row["amount_ht"]), align="R")
        pdf.cell(26, row_h, euros(row["amount_ttc"]) + "  ", align="R")
        pdf.set_y(y + row_h)
        fill = not fill

    # Totals
    if pdf.get_y() > 250:
        pdf.add_page()
    pdf.set_text_color(*accent)
    pdf.set_xy(110, pdf.get_y() + 6)
    pdf.set_font_size(11)
    pdf.cell(40, 7, "Total HT")
    pdf.set_font_size(12)
    pdf.cell(44, 7, euros(document.amount_ht), align="R")
    pdf.set_xy(110, pdf.get_y() + 7)
    pdf.set_font_size(11)
    pdf.cell(40, 7, f"TVA {document.vat_rate:.2f} %")
    pdf.cell(44, 7, euros(document.vat_amount), align="R")
    pdf.set_xy(110, pdf.get_y() + 8)
    pdf.set_font_size(12)
    pdf.cell(40, 8, "Total TTC")
    pdf.set_font_size(16)
    pdf.cell(44, 8, euros(document.amount_ttc), align="R")

    pdf.set_text_color(110, 116, 128)
    pdf.set_font_size(8)
    pdf.set_xy(left, 285)
    note = {
        "invoice": "Payable à réception",
        "quote": "Devis valable selon conditions",
        "credit_note": "Avoir à déduire",
    }.get(kind, "")
    pdf.cell(0, 4, f"{note} · TVA {document.vat_rate:.2f} % · {company.denomination}")

    return bytes(pdf.output())


def render_invoice_pdf(invoice, company) -> bytes:
    return render_document_pdf(invoice, company, kind="invoice")


def render_quote_pdf(quote, company) -> bytes:
    return render_document_pdf(quote, company, kind="quote")


def render_credit_note_pdf(credit_note, company) -> bytes:
    return render_document_pdf(credit_note, company, kind="credit_note")
