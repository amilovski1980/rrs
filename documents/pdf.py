"""PDF facture / devis / avoir, multi-pages, thèmes société.

La mise en page reprend la feuille de facture classique : logo et société en
en-tête, filet de couleur, grand titre, coordonnées client, tableau lignes,
totaux à droite et bandeau légal en pied de page.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
import re

from django.utils import timezone
from fpdf import FPDF

from .vat import vat_mentions

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

KIND_CLIENT_LABELS = {
    "invoice": "FACTURÉ À",
    "quote": "DESTINATAIRE",
    "credit_note": "CLIENT",
}

KIND_NOTES = {
    "invoice": "Règlement à 30 jours.",
    "quote": "Devis valable 30 jours.",
    "credit_note": "Avoir à déduire de la facture d'origine.",
}

INK = (12, 21, 28)
MUTED = (65, 72, 84)
LINE = (226, 230, 236)
WHITE = (255, 255, 255)


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


def _pct(value) -> str:
    rate = Decimal(str(value or 0)).quantize(Decimal("0.01"))
    if rate == rate.to_integral():
        return f"{int(rate)} %"
    return f"{rate.normalize()} %"


def _darken(color, factor: float = 0.35):
    return tuple(int(channel * (1 - factor)) for channel in color)


def _pale(color, factor: float = 0.9):
    return tuple(int(channel + (255 - channel) * factor) for channel in color)


def _siret(company) -> str:
    data = company.source_data if isinstance(getattr(company, "source_data", None), dict) else {}
    digits = "".join(ch for ch in str(data.get("siret") or "") if ch.isdigit())
    return digits if len(digits) == 14 else ""


def _format_siret(digits: str) -> str:
    digits = "".join(ch for ch in str(digits or "") if ch.isdigit())
    if len(digits) == 14:
        return f"{digits[:3]} {digits[3:6]} {digits[6:9]} {digits[9:]}"
    return digits


def _tva_number(company) -> str:
    """Numéro de TVA intracommunautaire saisi, officiel ou calculé depuis le SIREN."""
    from .vat import format_vat_number

    return format_vat_number(getattr(company, "tva_intra_number", ""))


def _wrap(pdf: FPDF, text: str, width: float, limit: int = 8) -> list[str]:
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
    return lines[:limit]


class DocumentPDF(FPDF):
    def __init__(self, accent, band, kind_title, left, content_w, columns, number):
        super().__init__(format="A4", unit="mm")
        self.accent = accent
        self.band = band
        self.kind_title = kind_title
        self.left = left
        self.content_w = content_w
        self.columns = columns
        self.number = number
        self.pale = _pale(accent)
        self.footer_lines = ("", "")
        self.set_auto_page_break(auto=True, margin=24)

    def header(self):
        if self.page_no() <= 1:
            return
        self.set_font("DejaVu", size=8)
        self.set_text_color(*self.accent)
        self.set_xy(self.left, 10)
        self.cell(0, 5, f"{self.kind_title} {self.number} — suite")
        self._table_header(16)

    def footer(self):
        self.set_fill_color(*self.band)
        self.rect(0, 279, 210, 18, "F")
        self.set_text_color(*WHITE)
        self.set_font("DejaVu", size=7.5)
        self.set_xy(12, 284)
        self.cell(186, 4, self.footer_lines[0], align="C")
        self.set_xy(12, 289)
        self.cell(186, 4, self.footer_lines[1], align="C")
        self.set_font("DejaVu", size=6.5)
        self.set_xy(0, 292.5)
        self.cell(198, 3.5, f"Page {self.page_no()}/{{nb}}", align="R")

    def _table_header(self, y: float):
        self.set_fill_color(*self.band)
        self.set_text_color(*WHITE)
        self.set_font("DejaVu", size=7.5)
        x = self.left
        for width, label, align in self.columns:
            self.set_xy(x, y)
            pad = "  " if align == "L" else ""
            self.cell(width, 8, pad + label, align=align, fill=True)
            x += width
        self.set_text_color(*INK)
        self.set_y(y + 8)


def _columns(width: float):
    parts = (
        (0.38, "DESCRIPTION", "L"),
        (0.09, "QTÉ", "R"),
        (0.13, "UNITÉ", "L"),
        (0.15, "PRIX HT", "R"),
        (0.09, "TVA", "R"),
        (0.16, "TTC", "R"),
    )
    raw = [round(width * share, 2) for share, _label, _align in parts]
    raw[-1] = round(width - sum(raw[:-1]), 2)
    return [(raw[i], parts[i][1], parts[i][2]) for i in range(len(parts))]


def _line_items(document):
    """Normalise les lignes (facture/devis) ou fabrique une ligne héritée."""
    reverse_charge = bool(getattr(document, "reverse_charge", False))
    lines = list(getattr(document, "lines", None).all()) if hasattr(document, "lines") else []
    if lines:
        rows = []
        for line in lines:
            product = getattr(line, "product", None)
            description = line.description or ""
            product_label = getattr(product, "label", "") if product else ""
            if product_label and product_label != description:
                title, details = product_label, description
            else:
                title, details = description, ""
            vat_rate = Decimal("0.00") if reverse_charge else line.vat_rate
            amount_ht = line.amount_ht
            amount_ttc = (
                amount_ht
                if reverse_charge
                else getattr(line, "amount_ttc", None)
                or (amount_ht * (Decimal("1") + line.vat_rate / Decimal("100"))).quantize(
                    Decimal("0.01")
                )
            )
            rows.append(
                {
                    "title": title,
                    "details": details,
                    "description": description,
                    "quantity": line.quantity,
                    "unit": (getattr(product, "unit", "") if product else "") or "unité",
                    "unit_price": line.unit_price,
                    "vat_rate": vat_rate,
                    "amount_ht": amount_ht,
                    "amount_ttc": amount_ttc,
                }
            )
        return rows
    client_name, _siren, _address = _client_fields(document)
    label = "Avoir" if hasattr(document, "invoice") and not hasattr(document, "client_name") else "Prestation"
    return [
        {
            "title": f"{label} — montant global",
            "details": "Prestation facturée au montant global, sans détail de lignes.",
            "description": f"{label} — montant global",
            "quantity": Decimal("1"),
            "unit": "unité",
            "unit_price": document.amount_ht,
            "vat_rate": Decimal("0.00") if reverse_charge else document.vat_rate,
            "amount_ht": document.amount_ht,
            "amount_ttc": document.amount_ht if reverse_charge else document.amount_ttc,
        }
    ]


def _client_fields(document):
    client = getattr(document, "client", None)
    name = getattr(document, "client_name", None) or getattr(client, "name", "")
    siren = getattr(document, "client_siren", "") or getattr(client, "siren", "")
    address = getattr(client, "address", "") if client else ""
    return name or "Client", siren or "", address or ""


def _client_number(document) -> str:
    client = getattr(document, "client", None)
    if client is None:
        return ""
    slug = re.sub(r"[^A-Z0-9]+", "-", str(client.name or "").upper()).strip("-")
    return f"CLI-{slug[:24]}" if slug else ""


def _meta_rows(document, kind: str, when: str):
    due = timezone.localtime(document.created_at) + timedelta(days=30)
    if kind == "credit_note":
        invoice = getattr(document, "invoice", None)
        return [
            ("Date de l'avoir", when),
            ("Facture d'origine", getattr(invoice, "number", "") or ""),
            ("N° client", _client_number(document)),
        ]
    if kind == "quote":
        return [
            ("Date du devis", when),
            ("Valable jusqu'au", due.strftime("%d/%m/%Y")),
            ("N° client", _client_number(document)),
        ]
    return [
        ("Date de facturation", when),
        ("Date d'échéance", due.strftime("%d/%m/%Y")),
        ("N° client", _client_number(document)),
    ]


def _vat_lines(rows):
    buckets: dict[Decimal, Decimal] = {}
    for row in rows:
        rate = Decimal(str(row["vat_rate"])).quantize(Decimal("0.01"))
        vat = (Decimal(str(row["amount_ttc"])) - Decimal(str(row["amount_ht"]))).quantize(Decimal("0.01"))
        buckets[rate] = buckets.get(rate, Decimal("0.00")) + vat
    return sorted(buckets.items(), key=lambda item: item[0])


def _draw_first_header(pdf: DocumentPDF, company, kind: str, document):
    left = pdf.left
    right = 16
    content_w = pdf.content_w
    accent = pdf.accent

    if company.logo:
        try:
            pdf.image(BytesIO(bytes(company.logo)), x=left, y=14, h=25)
        except Exception:
            pass

    pdf.set_text_color(*INK)
    pdf.set_font("DejaVu", size=17)
    pdf.set_xy(70, 14)
    pdf.cell(124, 8, (company.denomination or "")[:70], align="R")

    company_lines = []
    if company.address:
        company_lines.append(company.address[:110])
    siret = _siret(company)
    identity = [f"SIRET : {_format_siret(siret)}" if siret else f"SIREN : {company.siren}"]
    tva_number = _tva_number(company)
    if tva_number:
        identity.append(f"TVA : {tva_number}")
    company_lines.append("  |  ".join(identity))
    slogan = (getattr(company, "slogan", "") or "").strip()
    if slogan:
        company_lines.append(slogan[:120])

    pdf.set_font("DejaVu", size=8.5)
    pdf.set_text_color(*MUTED)
    y = 24
    for line in company_lines[:4]:
        pdf.set_xy(70, y)
        pdf.cell(124, 5, line, align="R")
        y += 5

    pdf.set_draw_color(*accent)
    pdf.set_line_width(0.8)
    pdf.line(left, 52, 210 - right, 52)

    pdf.set_text_color(*INK)
    pdf.set_font("DejaVu", size=27)
    pdf.set_xy(left, 58)
    pdf.cell(100, 12, pdf.kind_title)
    pdf.set_text_color(*accent)
    pdf.set_font("DejaVu", size=13)
    pdf.set_xy(left, 72)
    pdf.cell(100, 7, f"N° {document.number}")

    when = timezone.localtime(document.created_at).strftime("%d/%m/%Y")
    meta_y = 61
    for label, value in _meta_rows(document, kind, when):
        pdf.set_text_color(*MUTED)
        pdf.set_font("DejaVu", size=8.5)
        pdf.set_xy(116, meta_y)
        pdf.cell(42, 6, label)
        pdf.set_text_color(*INK)
        pdf.set_xy(158, meta_y)
        pdf.cell(36, 6, value, align="R")
        meta_y += 7.5

    client_name, client_siren, client_address = _client_fields(document)
    client_y = 94
    pdf.set_text_color(*accent)
    pdf.set_font("DejaVu", size=8)
    pdf.set_xy(left, client_y)
    pdf.cell(content_w, 4, KIND_CLIENT_LABELS.get(kind, "FACTURÉ À"))
    pdf.set_text_color(*INK)
    pdf.set_font("DejaVu", size=12)
    pdf.set_xy(left, client_y + 6)
    pdf.cell(content_w, 6, (client_name or "Client")[:80])

    client_lines = []
    if client_address:
        client_lines.extend(_wrap(pdf, client_address, content_w - 2, limit=2))
    if client_siren:
        client_lines.append(f"SIREN {client_siren}")
    client = getattr(document, "client", None)
    legal_form = (getattr(client, "legal_form", "") if client else "") or ""
    rcs = (getattr(client, "rcs", "") if client else "") or ""
    if legal_form:
        client_lines.append(f"Forme juridique : {legal_form}")
    if rcs:
        client_lines.append(f"RCS : {rcs}")
    client_tva = str(
        getattr(document, "client_tva_intra", "") or getattr(client, "tva_intra", "") or ""
    ).strip()
    if client_tva:
        from .vat import format_vat_number

        client_lines.append(f"TVA intracommunautaire : {format_vat_number(client_tva)}")

    pdf.set_text_color(*MUTED)
    pdf.set_font("DejaVu", size=9)
    y = client_y + 13
    for line in client_lines[:5]:
        pdf.set_xy(left, y)
        pdf.cell(content_w, 4.5, line)
        y += 4.5

    table_y = max(130, y + 5)
    pdf._table_header(table_y)


def render_document_pdf(document, company, kind: str = "invoice") -> bytes:
    theme = company.invoice_theme if company.invoice_theme in ACCENTS else "azur"
    accent = ACCENTS[theme]
    band = _darken(accent, 0.35)
    kind_title = KIND_TITLES.get(kind, "FACTURE")
    rows = _line_items(document)
    left = 16
    right = 16
    content_w = 210 - left - right
    columns = _columns(content_w)

    pdf = DocumentPDF(accent, band, kind_title, left, content_w, columns, document.number)
    pdf.alias_nb_pages()
    pdf.add_font("DejaVu", "", str(FONT))
    pdf.set_font("DejaVu", size=9)
    pdf.add_page()
    _draw_first_header(pdf, company, kind, document)

    desc_w = columns[0][0]
    for row in rows:
        title_chunks = _wrap(pdf, row["title"] or row["description"] or "", desc_w - 4)
        title_h = max(7.5, 4.5 * len(title_chunks) + 2.8)
        detail_chunks = _wrap(pdf, row["details"], desc_w - 4) if row["details"] else []
        detail_h = max(0, 4.0 * len(detail_chunks) + 1.5)
        row_h = title_h + detail_h
        if pdf.get_y() + row_h > 252:
            pdf.add_page()
        y = pdf.get_y()
        pdf.set_fill_color(*pdf.pale)
        pdf.rect(left, y, content_w, row_h, "F")
        pdf.set_text_color(*INK)
        pdf.set_font("DejaVu", size=9)
        for index, chunk in enumerate(title_chunks):
            pdf.set_xy(left + 2, y + 1.5 + index * 4.5)
            pdf.cell(desc_w - 4, 4.5, chunk)
        if detail_chunks:
            pdf.set_text_color(*MUTED)
            pdf.set_font("DejaVu", size=8.5)
            for index, chunk in enumerate(detail_chunks):
                pdf.set_xy(left + 2, y + title_h + 1 + index * 4.0)
                pdf.cell(desc_w - 4, 4.0, chunk)

        values = (
            _qty(row["quantity"]),
            (row["unit"] or "unité")[:18],
            euros(row["unit_price"]),
            _pct(row["vat_rate"]),
            euros(row["amount_ht"]),
            euros(row["amount_ttc"]),
        )
        cursor = left + desc_w
        pdf.set_text_color(*INK)
        pdf.set_font("DejaVu", size=8.5)
        value_y = y + 1.5
        for (width, _label, align), value in zip(columns[1:], values):
            pdf.set_xy(cursor, value_y)
            pdf.cell(width - 1.5, 4.5, value, align=align)
            cursor += width

        pdf.set_draw_color(*LINE)
        pdf.set_line_width(0.15)
        pdf.line(left, y + row_h, left + content_w, y + row_h)
        pdf.set_y(y + row_h)

    if pdf.get_y() > 235:
        pdf.add_page()

    box_w = 95
    box_x = 210 - right - box_w
    y = pdf.get_y() + 8
    pdf.set_text_color(*INK)
    pdf.set_font("DejaVu", size=9)
    pdf.set_xy(box_x, y)
    pdf.cell(box_w * 0.58, 7, "Sous-total HT")
    pdf.cell(box_w * 0.42, 7, euros(document.amount_ht), align="R")
    y += 7
    vat_lines = _vat_lines(rows)
    reverse_charge = bool(getattr(document, "reverse_charge", False))
    for rate, amount in vat_lines:
        label = f"TVA {_pct(rate)}"
        if reverse_charge and rate == 0:
            label += " (autoliquidation)"
        pdf.set_xy(box_x, y)
        pdf.cell(box_w * 0.58, 7, label)
        pdf.cell(box_w * 0.42, 7, euros(amount), align="R")
        y += 7
    if not vat_lines and reverse_charge:
        pdf.set_xy(box_x, y)
        pdf.cell(box_w * 0.58, 7, "TVA 0 % (autoliquidation)")
        pdf.cell(box_w * 0.42, 7, euros(Decimal("0.00")), align="R")
        y += 7

    pdf.set_fill_color(*band)
    pdf.set_text_color(*WHITE)
    pdf.set_font("DejaVu", size=10)
    pdf.set_xy(box_x, y + 1)
    pdf.cell(box_w * 0.58, 9, "  Montant Total TTC (EUR)", fill=True)
    pdf.set_font("DejaVu", size=11)
    pdf.cell(box_w * 0.42, 9, euros(document.amount_ttc) + "  ", align="R", fill=True)
    y += 11

    if kind == "invoice":
        paid = getattr(document, "amount_paid", Decimal("0.00"))
        remaining = getattr(document, "amount_remaining", document.amount_ttc)
        pdf.set_text_color(*INK)
        pdf.set_font("DejaVu", size=9)
        pdf.set_xy(box_x, y)
        pdf.cell(box_w * 0.58, 7, "Montant payé")
        pdf.cell(box_w * 0.42, 7, euros(paid), align="R")
        y += 9
        pdf.set_draw_color(*accent)
        pdf.set_line_width(0.5)
        pdf.line(box_x, y, box_x + box_w, y)
        pdf.set_text_color(*accent)
        pdf.set_font("DejaVu", size=11)
        pdf.set_xy(box_x, y + 1)
        pdf.cell(box_w * 0.58, 8, "Montant à payer (EUR)")
        pdf.cell(box_w * 0.42, 8, euros(remaining), align="R")
    else:
        pdf.set_text_color(*accent)
        pdf.set_font("DejaVu", size=10)
        pdf.set_xy(box_x, y)
        label = "Montant à payer (EUR)" if kind == "quote" else "Montant de l'avoir (EUR)"
        pdf.cell(box_w * 0.58, 8, label)
        pdf.cell(box_w * 0.42, 8, euros(document.amount_ttc), align="R")

    y += 12
    note = KIND_NOTES.get(kind, "")
    if note:
        pdf.set_text_color(*MUTED)
        pdf.set_font("DejaVu", size=8.5)
        pdf.set_xy(left, y)
        pdf.cell(content_w, 5, note)

    legal = list(vat_mentions(document, company))
    bank_iban = (getattr(company, "bank_iban", "") or "").strip()
    if bank_iban and kind in ("invoice", "quote"):
        bank_line = f"Règlement par virement : IBAN {bank_iban}"
        bank_bic = (getattr(company, "bank_bic", "") or "").strip()
        bank_name = (getattr(company, "bank_name", "") or "").strip()
        if bank_bic:
            bank_line += f" - BIC {bank_bic}"
        if bank_name:
            bank_line += f" - {bank_name}"
        legal.append(bank_line)
    if kind == "invoice":
        legal.append(
            "En cas de retard de paiement : pénalités de trois fois le taux d'intérêt légal "
            "et indemnité forfaitaire de 40 € (art. L441-10 du code commerce)."
        )
    if legal:
        pdf.set_text_color(*MUTED)
        pdf.set_font("DejaVu", size=7)
        pdf.set_xy(left, min(y + 6, 263))
        pdf.multi_cell(content_w - 10, 3.5, "\n".join(legal))

    siret = _siret(company)
    tva_number = _tva_number(company)
    footer_1 = (company.denomination or "").strip()
    footer_1 += f" — SIRET {_format_siret(siret)}" if siret else f" — SIREN {company.siren}"
    if tva_number:
        footer_1 += f" — TVA {tva_number}"
    footer_2 = (company.address or "").strip()
    if slogan := (getattr(company, "slogan", "") or "").strip():
        footer_2 = f"{footer_2} — {slogan}" if footer_2 else slogan
    pdf.footer_lines = (footer_1[:150], footer_2[:150])

    return bytes(pdf.output())


def render_invoice_pdf(invoice, company) -> bytes:
    return render_document_pdf(invoice, company, kind="invoice")


def render_quote_pdf(quote, company) -> bytes:
    return render_document_pdf(quote, company, kind="quote")


def render_credit_note_pdf(credit_note, company) -> bytes:
    return render_document_pdf(credit_note, company, kind="credit_note")
