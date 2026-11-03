"""Facture PDF, une page A4, selon le modèle de la société."""
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
}


def euros(value):
    whole, cents = f"{value:.2f}".split(".")
    grouped = f"{int(whole):,}".replace(",", " ")
    return f"{grouped},{cents} €"


def render_invoice_pdf(invoice, company) -> bytes:
    theme = company.invoice_theme if company.invoice_theme in ACCENTS else "azur"
    accent = ACCENTS[theme]
    ink = (255, 255, 255) if theme == "azur" else (28, 32, 38)
    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()
    pdf.add_font("DejaVu", "", str(FONT))
    pdf.set_font("DejaVu", size=11)

    if theme == "azur":
        pdf.set_fill_color(*accent)
        pdf.rect(0, 0, 210, 46, "F")
    elif theme == "carmin":
        pdf.set_fill_color(*accent)
        pdf.rect(0, 0, 7, 297, "F")
    elif theme == "sauge":
        pdf.set_fill_color(244, 250, 246)
        pdf.rect(0, 0, 210, 297, "F")
    else:
        pdf.set_draw_color(*accent)
        pdf.set_line_width(0.6)
        pdf.line(16, 44, 194, 44)

    x = 18 if theme == "carmin" else 16
    if company.logo:
        try:
            pdf.image(BytesIO(bytes(company.logo)), x=x, y=12, h=16)
            x += 22
        except Exception:
            pass

    pdf.set_text_color(*ink)
    pdf.set_xy(x, 12)
    pdf.set_font_size(15)
    pdf.cell(100, 7, (company.denomination or "")[:48])
    pdf.set_font_size(9)
    lines = []
    if company.address:
        lines.append(company.address)
    lines.append(f"{company.forme} · SIREN {company.siren}")
    if company.phone:
        lines.append(company.phone)
    if company.email:
        lines.append(company.email)
    pdf.set_xy(x, 20)
    pdf.multi_cell(100, 4.2, "\n".join(lines))

    pdf.set_text_color(*(accent if theme != "azur" else (255, 255, 255)))
    pdf.set_xy(120, 12)
    pdf.set_font_size(16)
    pdf.cell(74, 8, "FACTURE", align="R")
    pdf.set_text_color(*((214, 228, 255) if theme == "azur" else (40, 44, 52)))
    pdf.set_font_size(10)
    pdf.set_xy(120, 22)
    pdf.cell(74, 5, invoice.number, align="R")
    when = timezone.localtime(invoice.created_at).strftime("%d/%m/%Y")
    pdf.set_xy(120, 28)
    pdf.cell(74, 5, when, align="R")
    pdf.set_xy(120, 34)
    pdf.cell(74, 5, invoice.get_status_display(), align="R")

    pdf.set_text_color(40, 44, 52)
    pdf.set_xy(16, 58)
    pdf.set_font_size(8)
    pdf.set_text_color(*accent)
    pdf.cell(0, 4, "FACTURÉ À")
    pdf.set_text_color(28, 32, 38)
    pdf.set_xy(16, 64)
    pdf.set_font_size(13)
    pdf.cell(0, 6, invoice.client_name[:80])
    pdf.set_font_size(9)
    pdf.set_xy(16, 71)
    client = f"SIREN {invoice.client_siren}" if invoice.client_siren else "Client"
    pdf.cell(0, 5, client)

    pdf.set_fill_color(*accent)
    pdf.set_text_color(255, 255, 255)
    pdf.set_xy(16, 84)
    pdf.set_font_size(9)
    pdf.cell(96, 8, "  Désignation", fill=True)
    pdf.cell(26, 8, "HT", align="R", fill=True)
    pdf.cell(26, 8, "TVA", align="R", fill=True)
    pdf.cell(30, 8, "TTC  ", align="R", fill=True)

    pdf.set_text_color(28, 32, 38)
    pdf.set_fill_color(248, 249, 251)
    pdf.set_xy(16, 92)
    pdf.set_font_size(10)
    label = f"Prestation — {invoice.client_name}"[:70]
    pdf.cell(96, 10, "  " + label, fill=True)
    pdf.cell(26, 10, euros(invoice.amount_ht), align="R", fill=True)
    pdf.cell(26, 10, euros(invoice.vat_amount), align="R", fill=True)
    pdf.cell(30, 10, euros(invoice.amount_ttc) + "  ", align="R", fill=True)

    pdf.set_text_color(*accent)
    pdf.set_xy(110, 112)
    pdf.set_font_size(11)
    pdf.cell(40, 8, "Total")
    pdf.set_font_size(16)
    pdf.cell(44, 8, euros(invoice.amount_ttc), align="R")

    pdf.set_text_color(110, 116, 128)
    pdf.set_font_size(8)
    pdf.set_xy(16, 270)
    pdf.cell(0, 4, f"TVA {invoice.vat_rate:.2f} % · Payable à réception · {company.denomination}")

    return bytes(pdf.output())
