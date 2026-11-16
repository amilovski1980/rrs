"""PDF facture / devis / avoir, multi-pages, thèmes société.

Cinq mises en page inspirées des modèles A4 de la palette :
Royal Wave, Emerald Prestige, Noir & Or Impérial, Bordeaux & Champagne,
Saphir & Argent. Les textes légaux et les libellés comptables restent
identiques à l'ancien rendu.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import re

from django.utils import timezone
from fpdf import FPDF

from .vat import vat_mentions

FONT = Path(__file__).resolve().parent / "fonts" / "DejaVuSans.ttf"

WHITE = (255, 255, 255)
INK = (12, 21, 28)
MUTED = (80, 88, 100)
LINE = (226, 230, 236)

PALETTES = {
    "azur": {
        "ink": (11, 61, 145),
        "accent": (0, 168, 232),
        "soft": (238, 246, 255),
        "line": (207, 224, 247),
        "layout": "royal",
    },
    "carmin": {
        "ink": (180, 35, 24),
        "accent": (234, 179, 8),
        "soft": (255, 245, 243),
        "line": (241, 212, 207),
        "layout": "bordeaux",
    },
    "encre": {
        "ink": (22, 22, 22),
        "accent": (212, 175, 55),
        "soft": (248, 246, 240),
        "line": (230, 223, 207),
        "layout": "imperial",
    },
    "sauge": {
        "ink": (31, 122, 77),
        "accent": (14, 116, 144),
        "soft": (239, 250, 244),
        "line": (207, 233, 220),
        "layout": "emerald",
    },
    "graphite": {
        "ink": (45, 52, 64),
        "accent": (148, 163, 184),
        "soft": (244, 246, 248),
        "line": (216, 222, 230),
        "layout": "royal",
    },
    "indigo": {
        "ink": (79, 70, 229),
        "accent": (59, 130, 246),
        "soft": (238, 242, 255),
        "line": (214, 217, 251),
        "layout": "sapphire",
    },
    "terra": {
        "ink": (180, 83, 49),
        "accent": (234, 179, 8),
        "soft": (253, 245, 239),
        "line": (240, 217, 201),
        "layout": "bordeaux",
    },
    "vert": {
        "ink": (5, 120, 85),
        "accent": (52, 211, 153),
        "soft": (239, 250, 244),
        "line": (207, 233, 220),
        "layout": "emerald",
    },
    "monochrome": {
        "ink": (24, 24, 24),
        "accent": (120, 120, 120),
        "soft": (246, 246, 246),
        "line": (224, 224, 224),
        "layout": "minimal",
    },
}

# Compatibilité avec d'éventuels imports historiques.
ACCENTS = {key: value["ink"] for key, value in PALETTES.items()}

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


def euros(value) -> str:
    value = Decimal(str(value or 0)).quantize(Decimal("0.01"))
    whole, cents = f"{value:.2f}".split(".")
    grouped = f"{int(whole):,}".replace(",", " ")
    return f"{grouped},{cents} €"


def _qty(value) -> str:
    quantity = Decimal(str(value)).normalize()
    text = format(quantity, "f")
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


def _mix(color, other, ratio: float = 0.5):
    return tuple(int(a * (1 - ratio) + b * ratio) for a, b in zip(color, other))


def _luminance(color) -> float:
    channels = []
    for value in color:
        channel = value / 255
        channels.append(
            channel / 12.92
            if channel <= 0.03928
            else ((channel + 0.055) / 1.055) ** 2.4
        )
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(first, second) -> float:
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _readable_on(background, preferred, minimum: float = 3.0):
    """Garde la couleur d'accent si elle reste lisible, sinon passe au blanc."""
    return preferred if _contrast(background, preferred) >= minimum else WHITE


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
    manager = getattr(document, "lines", None)
    if manager is not None and hasattr(manager, "all"):
        lines = list(manager.all())
    elif manager is not None:
        lines = list(manager)
    else:
        lines = []
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
    due = getattr(document, "effective_due_date", None)
    if due is None:
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
            ("Valable jusqu'au", (document.valid_until or due).strftime("%d/%m/%Y")),
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


class DocumentPDF(FPDF):
    def __init__(self, palette, kind_title, left, content_w, columns, number):
        super().__init__(format="A4", unit="mm")
        self.palette = palette
        self.ink = palette["ink"]
        self.accent = palette["accent"]
        self.soft = palette["soft"]
        self.line_color = palette["line"]
        self.layout = palette["layout"]
        self.kind_title = kind_title
        self.left = left
        self.content_w = content_w
        self.columns = columns
        self.number = number
        self.pale = _pale(self.accent)
        self.band = _darken(self.ink, 0.18)
        self.footer_lines = ("", "")
        self.set_auto_page_break(auto=True, margin=28)
        self.set_margins(left, 12, 16)

    def header(self):
        if self.page_no() <= 1:
            return
        self.set_fill_color(*self.ink)
        self.rect(0, 0, 210, 15, "F")
        self.set_text_color(*self._footer_text())
        self.set_font("DejaVu", size=8.5)
        self.set_xy(self.left, 4.5)
        self.cell(0, 5, f"{self.kind_title} {self.number} — suite")
        self._table_header(17)

    def footer(self):
        dark = self.layout in ("royal", "imperial", "sapphire")
        if dark:
            self.set_fill_color(*self.ink)
            self.rect(0, 278, 210, 19, "F")
            self.set_draw_color(*self.accent)
            self.set_line_width(0.5)
            self.line(0, 278, 210, 278)
        else:
            self.set_fill_color(*self.soft)
            self.rect(0, 278, 210, 19, "F")
            self.set_draw_color(*self.accent)
            self.set_line_width(0.4)
            self.line(0, 278, 210, 278)
        self.set_text_color(*self._footer_text())
        self.set_font("DejaVu", size=7.2)
        self.set_xy(12, 282.5)
        self.cell(186, 4, self.footer_lines[0], align="C")
        self.set_font("DejaVu", size=6.5)
        self.set_xy(12, 287.2)
        self.cell(186, 4, self.footer_lines[1], align="C")
        self.set_xy(0, 291.5)
        self.cell(198, 3.5, f"Page {self.page_no()}/{{nb}}", align="R")

    def _footer_text(self):
        if self.layout == "imperial":
            return _readable_on(self.ink, self.accent)
        if self.layout in ("royal", "sapphire"):
            return WHITE
        return self.ink

    def _table_header(self, y: float):
        header_fill = self.soft if self.layout == "sapphire" else self.ink
        if self.layout == "imperial":
            header_text = _readable_on(self.ink, self.accent)
        elif self.layout == "sapphire":
            header_text = self.ink
        else:
            header_text = WHITE
        self.set_fill_color(*header_fill)
        self.rect(
            self.left,
            y,
            self.content_w,
            8,
            "F",
            round_corners=True,
            corner_radius=2,
        )
        self.set_text_color(*header_text)
        self.set_font("DejaVu", size=7.2)
        x = self.left
        for width, label, align in self.columns:
            self.set_xy(x, y)
            self.cell(width, 8, ("  " + label) if align == "L" else label, align=align)
            x += width
        self.set_draw_color(*self.accent)
        self.set_line_width(0.4)
        self.line(self.left, y + 8, self.left + self.content_w, y + 8)
        self.set_text_color(*self.ink)
        self.set_y(y + 8)


# ---------------------------------------------------------------------------
# Briques de mise en page
# ---------------------------------------------------------------------------
def _logo(pdf: DocumentPDF, company, x, y, height, on_dark=False):
    if not company.logo:
        return 0
    try:
        if on_dark:
            pdf.set_fill_color(*WHITE)
            pdf.rect(
                x - 1.4,
                y - 1.4,
                height + 2.8,
                height + 2.8,
                "F",
                round_corners=True,
                corner_radius=1.5,
            )
        pdf.image(BytesIO(bytes(company.logo)), x=x, y=y, h=height)
        return height
    except Exception:
        return 0


def _company_lines(pdf: DocumentPDF, company, width, *, dark=False):
    pdf.set_font("DejaVu", size=7.5)
    color = _pale(pdf.accent, 0.55) if dark else MUTED
    lines = []
    if company.address:
        lines.extend(_wrap(pdf, company.address, width, 2))
    siret = _siret(company)
    identity = [f"SIRET {_format_siret(siret)}" if siret else f"SIREN {company.siren}"]
    tva_number = _tva_number(company)
    if tva_number:
        identity.append(f"TVA {tva_number}")
    lines.append(" · ".join(identity))
    slogan = (getattr(company, "slogan", "") or "").strip()
    if slogan:
        lines.append(slogan[:100])
    return lines[:4], color


def _client_lines(pdf: DocumentPDF, document, width):
    pdf.set_font("DejaVu", size=7.5)
    _name, siren, address = _client_fields(document)
    lines = []
    if address:
        lines.extend(_wrap(pdf, address, width, 2))
    if siren:
        lines.append(f"SIREN {siren}")
    client = getattr(document, "client", None)
    legal_form = (getattr(client, "legal_form", "") if client else "") or ""
    rcs = (getattr(client, "rcs", "") if client else "") or ""
    if legal_form:
        lines.append(f"Forme juridique : {legal_form}")
    if rcs:
        lines.append(f"RCS : {rcs}")
    client_tva = str(
        getattr(document, "client_tva_intra", "") or getattr(client, "tva_intra", "") or ""
    ).strip()
    if client_tva:
        from .vat import format_vat_number

        lines.append(f"TVA intracommunautaire : {format_vat_number(client_tva)}")
    return lines[:5]


def _fit(pdf: DocumentPDF, text: str, width: float, size: float) -> str:
    pdf.set_font("DejaVu", size=size)
    return _wrap(pdf, text or "", width, 1)[0]


def _card(
    pdf: DocumentPDF,
    x,
    y,
    width,
    height,
    label,
    name,
    lines,
    *,
    fill=WHITE,
    border=None,
    label_color=None,
    name_color=None,
    left_accent=None,
    top_accent=None,
):
    border = border or pdf.line_color
    label_color = label_color or pdf.accent
    name_color = name_color or pdf.ink
    pdf.set_fill_color(*fill)
    pdf.set_draw_color(*border)
    pdf.set_line_width(0.25)
    pdf.rect(
        x,
        y,
        width,
        height,
        "DF",
        round_corners=True,
        corner_radius=3,
    )
    if left_accent:
        pdf.set_fill_color(*left_accent)
        pdf.rect(x, y + 3, 1.2, height - 6, "F")
    if top_accent:
        pdf.set_fill_color(*top_accent)
        pdf.rect(x + 3, y, width - 6, 1.1, "F")
    pdf.set_text_color(*label_color)
    pdf.set_font("DejaVu", size=6.8)
    pdf.set_xy(x + 5, y + 5)
    pdf.cell(width - 10, 4, (label or "").upper())
    pdf.set_text_color(*name_color)
    pdf.set_font("DejaVu", size=10.5)
    pdf.set_xy(x + 5, y + 10.5)
    pdf.cell(width - 10, 5.5, _fit(pdf, name or "", width - 10, 10.5))
    pdf.set_text_color(*MUTED)
    pdf.set_font("DejaVu", size=7.4)
    yy = y + 18
    for line in (lines or [])[:5]:
        pdf.set_xy(x + 5, yy)
        pdf.cell(width - 10, 4, line)
        yy += 4


def _meta_block(pdf, document, kind, x, y, width, label_color, value_color, line_color):
    for label, value in _meta_rows(document, kind, timezone.localtime(document.created_at).strftime("%d/%m/%Y")):
        pdf.set_draw_color(*line_color)
        pdf.set_line_width(0.15)
        pdf.line(x, y + 5.4, x + width, y + 5.4)
        pdf.set_text_color(*label_color)
        pdf.set_font("DejaVu", size=7.1)
        pdf.set_xy(x, y)
        pdf.cell(width * 0.55, 4, label)
        pdf.set_text_color(*value_color)
        pdf.set_font("DejaVu", size=8)
        pdf.set_xy(x + width * 0.55, y)
        pdf.cell(width * 0.45, 4, value or "", align="R")
        y += 6
    return y


def _meta_cells(pdf, document, kind, x, y, total_width, *, dark=False):
    labels = _meta_rows(document, kind, timezone.localtime(document.created_at).strftime("%d/%m/%Y"))
    cell_w = (total_width - 2 * 4) / 3
    for index, (label, value) in enumerate(labels):
        cx = x + index * (cell_w + 4)
        if dark:
            pdf.set_fill_color(*_mix(pdf.ink, WHITE, 0.12))
            pdf.set_draw_color(*pdf.accent)
            pdf.set_line_width(0.18)
            pdf.rect(cx, y, cell_w, 12, "DF", round_corners=True, corner_radius=2)
            label_color = _pale(pdf.accent, 0.45)
            value_color = WHITE
        else:
            pdf.set_fill_color(*pdf.soft)
            pdf.set_draw_color(*pdf.line_color)
            pdf.set_line_width(0.2)
            pdf.rect(cx, y, cell_w, 12, "DF", round_corners=True, corner_radius=2)
            label_color = pdf.accent
            value_color = pdf.ink
        pdf.set_text_color(*label_color)
        pdf.set_font("DejaVu", size=6.1)
        pdf.set_xy(cx + 3, y + 2)
        pdf.cell(cell_w - 6, 3.5, label.upper())
        pdf.set_text_color(*value_color)
        pdf.set_font("DejaVu", size=7.6)
        pdf.set_xy(cx + 3, y + 6)
        pdf.cell(cell_w - 6, 4, value or "")


def _header_royal(pdf, company, kind, document):
    accent = pdf.accent
    pdf.set_fill_color(*pdf.ink)
    pdf.rect(0, 0, 210, 54, "F")
    pdf.set_fill_color(*accent)
    pdf.polygon(
        [(0, 46), (28, 49), (61, 45), (97, 51), (140, 46), (178, 50), (210, 45), (210, 54), (0, 54)],
        fill=True,
    )
    pdf.set_fill_color(*_darken(pdf.ink, 0.1))
    pdf.polygon(
        [(0, 50), (42, 47), (82, 52), (126, 48), (166, 52), (210, 49), (210, 54), (0, 54)],
        fill=True,
    )
    _logo(pdf, company, 16, 12, 15, on_dark=True)
    pdf.set_text_color(*WHITE)
    pdf.set_font("DejaVu", size=13.5)
    pdf.set_xy(35, 12.5)
    pdf.cell(120, 6, _fit(pdf, company.denomination or "", 118, 13.5))
    pdf.set_text_color(*_pale(accent, 0.35))
    pdf.set_font("DejaVu", size=6.8)
    pdf.set_xy(35, 19.5)
    pdf.cell(120, 4, _fit(pdf, company.slogan or "Comptabilité des bâtisseurs", 118, 6.8))
    pdf.set_draw_color(*accent)
    pdf.set_text_color(*_pale(accent, 0.25))
    pdf.set_font("DejaVu", size=6.6)
    pdf.rect(151, 12.5, 43, 8, "D", round_corners=True, corner_radius=4)
    pdf.set_xy(151, 13.4)
    pdf.cell(43, 5, pdf.kind_title, align="C")

    pdf.set_text_color(*pdf.ink)
    pdf.set_font("DejaVu", size=27)
    pdf.set_xy(16, 59)
    pdf.cell(95, 11, pdf.kind_title)
    pdf.set_fill_color(*accent)
    pdf.rect(16, 70.5, 24, 1.2, "F")
    pdf.set_text_color(*accent)
    pdf.set_font("DejaVu", size=8.8)
    pdf.set_xy(16, 73)
    pdf.cell(95, 5, f"N° {document.number}")
    _meta_block(pdf, document, kind, 116, 59, 78, MUTED, pdf.ink, pdf.line_color)

    client_name, _siren, _address = _client_fields(document)
    _card(
        pdf,
        16,
        84,
        102,
        38,
        KIND_CLIENT_LABELS.get(kind, "FACTURÉ À"),
        client_name,
        _client_lines(pdf, document, 90),
        fill=WHITE,
        border=pdf.line_color,
        label_color=accent,
        name_color=pdf.ink,
    )
    company_lines, _color = _company_lines(pdf, company, 58)
    _card(
        pdf,
        124,
        84,
        70,
        38,
        "DE LA PART DE",
        company.denomination or "",
        company_lines,
        fill=pdf.soft,
        border=pdf.line_color,
        label_color=pdf.ink,
        name_color=pdf.ink,
    )
    pdf.set_y(129)


def _header_emerald(pdf, company, kind, document):
    accent = pdf.accent
    pdf.set_fill_color(*accent)
    pdf.rect(0, 0, 210, 50, "F")
    pdf.set_fill_color(*pdf.ink)
    pdf.polygon([(0, 0), (70, 0), (58, 50), (0, 50)], fill=True)
    pdf.set_fill_color(*_pale(accent, 0.45))
    pdf.polygon([(70, 0), (77, 0), (65, 50), (58, 50)], fill=True)
    pdf.set_text_color(*WHITE)
    pdf.set_font("DejaVu", size=26)
    pdf.set_xy(16, 13)
    pdf.cell(52, 10, pdf.kind_title)
    pdf.set_text_color(*_pale(accent, 0.35))
    pdf.set_font("DejaVu", size=7)
    pdf.set_xy(16, 24)
    pdf.cell(52, 4, f"N° {document.number}")
    _logo(pdf, company, 151, 9, 12, on_dark=True)
    pdf.set_text_color(*WHITE)
    pdf.set_font("DejaVu", size=10.5)
    pdf.set_xy(120, 22)
    pdf.cell(74, 5, _fit(pdf, company.denomination or "", 74, 10.5), align="R")
    pdf.set_text_color(*_pale(accent, 0.4))
    pdf.set_font("DejaVu", size=6.2)
    pdf.set_xy(120, 27)
    pdf.cell(74, 4, _fit(pdf, company.slogan or "Comptabilité des bâtisseurs", 74, 6.2), align="R")

    _meta_cells(pdf, document, kind, 16, 55, 178)
    client_name, _siren, _address = _client_fields(document)
    _card(
        pdf,
        16,
        75,
        102,
        38,
        KIND_CLIENT_LABELS.get(kind, "FACTURÉ À"),
        client_name,
        _client_lines(pdf, document, 90),
        fill=WHITE,
        border=pdf.line_color,
        label_color=accent,
        name_color=pdf.ink,
        left_accent=pdf.ink,
    )
    company_lines, _color = _company_lines(pdf, company, 56)
    _card(
        pdf,
        124,
        75,
        70,
        38,
        "DE LA PART DE",
        company.denomination or "",
        company_lines,
        fill=pdf.soft,
        border=pdf.line_color,
        label_color=accent,
        name_color=pdf.ink,
    )
    pdf.set_y(120)


def _header_imperial(pdf, company, kind, document):
    accent = pdf.accent
    pdf.set_fill_color(*pdf.ink)
    pdf.rect(0, 0, 210, 58, "F")
    pdf.set_draw_color(*accent)
    pdf.set_line_width(0.5)
    pdf.line(0, 4, 210, 4)
    pdf.line(0, 54, 210, 54)
    _logo(pdf, company, 97, 7, 11, on_dark=True)
    pdf.set_text_color(*accent)
    pdf.set_font("DejaVu", size=9.5)
    pdf.set_xy(0, 21)
    pdf.cell(210, 5, _fit(pdf, company.denomination or "", 170, 9.5), align="C")
    pdf.set_text_color(*_pale(accent, 0.35))
    pdf.set_font("DejaVu", size=6.2)
    pdf.set_xy(0, 26)
    pdf.cell(210, 4, _fit(pdf, company.slogan or "Comptabilité des bâtisseurs", 170, 6.2), align="C")
    pdf.set_text_color(*accent)
    pdf.set_font("DejaVu", size=21)
    pdf.set_xy(0, 32)
    pdf.cell(210, 8, pdf.kind_title, align="C")
    pdf.set_text_color(*_pale(accent, 0.45))
    pdf.set_font("DejaVu", size=6.8)
    pdf.set_xy(0, 43)
    pdf.cell(
        210,
        4,
        f"N° {document.number} · {timezone.localtime(document.created_at).strftime('%d/%m/%Y')}",
        align="C",
    )

    pdf.set_text_color(*accent)
    pdf.set_font("DejaVu", size=6.8)
    pdf.set_xy(16, 62)
    pdf.cell(178, 4, "DE LA PART DE")
    pdf.set_text_color(*pdf.ink)
    pdf.set_font("DejaVu", size=10.5)
    pdf.set_xy(16, 67)
    pdf.cell(178, 5, _fit(pdf, company.denomination or "", 178, 10.5))
    company_lines, _color = _company_lines(pdf, company, 170)
    pdf.set_text_color(*MUTED)
    pdf.set_font("DejaVu", size=7.4)
    y = 73
    for line in company_lines[:3]:
        pdf.set_xy(16, y)
        pdf.cell(178, 4, line)
        y += 4

    client_name, _siren, _address = _client_fields(document)
    pdf.set_draw_color(*accent)
    pdf.set_line_width(0.35)
    pdf.line(104.5, 90, 104.5, 118)
    _card(
        pdf,
        16,
        90,
        82,
        28,
        KIND_CLIENT_LABELS.get(kind, "FACTURÉ À"),
        client_name,
        _client_lines(pdf, document, 70),
        fill=WHITE,
        border=pdf.line_color,
        label_color=accent,
        name_color=pdf.ink,
    )
    _meta_block(pdf, document, kind, 114, 91, 80, MUTED, pdf.ink, pdf.line_color)
    pdf.set_y(124)


def _header_bordeaux(pdf, company, kind, document):
    accent = pdf.accent
    pdf.set_fill_color(*pdf.soft)
    pdf.rect(0, 0, 210, 68, "F")
    pdf.set_fill_color(*pdf.ink)
    pdf.polygon([(116, 0), (210, 0), (210, 68), (151, 68), (116, 51)], fill=True)
    pdf.set_draw_color(*accent)
    pdf.set_line_width(0.7)
    pdf.line(116, 51, 151, 68)
    _logo(pdf, company, 16, 12, 12)
    pdf.set_text_color(*pdf.ink)
    pdf.set_font("DejaVu", size=12.5)
    pdf.set_xy(31, 13)
    pdf.cell(78, 6, _fit(pdf, company.denomination or "", 76, 12.5))
    company_lines, _color = _company_lines(pdf, company, 78)
    pdf.set_text_color(*MUTED)
    pdf.set_font("DejaVu", size=7.2)
    y = 20
    for line in company_lines[:3]:
        pdf.set_xy(16, y)
        pdf.cell(92, 4, line)
        y += 4

    pdf.set_text_color(*WHITE)
    pdf.set_font("DejaVu", size=25)
    pdf.set_xy(121, 14)
    pdf.cell(72, 10, pdf.kind_title, align="R")
    pdf.set_text_color(*_pale(accent, 0.35))
    pdf.set_font("DejaVu", size=6.7)
    pdf.set_xy(121, 25)
    pdf.cell(72, 4, f"N° {document.number}", align="R")
    _meta_block(pdf, document, kind, 124, 33, 70, _pale(accent, 0.3), WHITE, _mix(pdf.ink, WHITE, 0.3))

    client_name, _siren, _address = _client_fields(document)
    _card(
        pdf,
        16,
        76,
        102,
        38,
        KIND_CLIENT_LABELS.get(kind, "FACTURÉ À"),
        client_name,
        _client_lines(pdf, document, 90),
        fill=WHITE,
        border=pdf.line_color,
        label_color=pdf.ink,
        name_color=pdf.ink,
        left_accent=pdf.ink,
    )
    bank_iban = (getattr(company, "bank_iban", "") or "").strip()
    bank_bic = (getattr(company, "bank_bic", "") or "").strip()
    payment_lines = []
    if bank_iban:
        payment_lines.append(f"IBAN {bank_iban}")
    if bank_bic:
        payment_lines.append(f"BIC {bank_bic}")
    payment_lines.append("Merci de rappeler le n° de facture.")
    _card(
        pdf,
        124,
        76,
        70,
        38,
        "RÈGLEMENT",
        "Virement bancaire",
        payment_lines,
        fill=pdf.soft,
        border=pdf.line_color,
        label_color=accent,
        name_color=pdf.ink,
    )
    pdf.set_y(121)


def _header_sapphire(pdf, company, kind, document):
    accent = pdf.accent
    pdf.set_fill_color(*pdf.ink)
    pdf.rect(0, 0, 210, 60, "F")
    pdf.set_fill_color(*accent)
    pdf.rect(0, 58, 210, 1.2, "F")
    pdf.set_text_color(*WHITE)
    pdf.set_font("DejaVu", size=26)
    pdf.set_xy(16, 12)
    pdf.cell(100, 10, pdf.kind_title)
    pdf.set_text_color(*_pale(accent, 0.35))
    pdf.set_font("DejaVu", size=7)
    pdf.set_xy(16, 23)
    pdf.cell(100, 4, f"N° {document.number}")
    _meta_cells(pdf, document, kind, 16, 32, 112, dark=True)

    _logo(pdf, company, 137, 10, 11, on_dark=True)
    pdf.set_text_color(*WHITE)
    pdf.set_font("DejaVu", size=9.5)
    pdf.set_xy(132, 23)
    pdf.cell(62, 5, _fit(pdf, company.denomination or "", 62, 9.5), align="R")
    company_lines, _color = _company_lines(pdf, company, 58, dark=True)
    pdf.set_text_color(*_pale(accent, 0.45))
    pdf.set_font("DejaVu", size=6.4)
    y = 29
    for line in company_lines[:2]:
        pdf.set_xy(132, y)
        pdf.cell(62, 3.6, line, align="R")
        y += 3.6

    client_name, _siren, _address = _client_fields(document)
    _card(
        pdf,
        16,
        75,
        104,
        38,
        KIND_CLIENT_LABELS.get(kind, "FACTURÉ À"),
        client_name,
        _client_lines(pdf, document, 92),
        fill=WHITE,
        border=pdf.line_color,
        label_color=accent,
        name_color=pdf.ink,
        top_accent=accent,
    )
    company_lines, _color = _company_lines(pdf, company, 58)
    _card(
        pdf,
        126,
        75,
        68,
        38,
        "DE LA PART DE",
        company.denomination or "",
        company_lines,
        fill=pdf.soft,
        border=pdf.line_color,
        label_color=pdf.ink,
        name_color=pdf.ink,
    )
    pdf.set_y(120)


def _header_classique(pdf, company, kind, document):
    pdf.set_draw_color(*pdf.accent)
    pdf.set_line_width(0.8)
    pdf.line(16, 30, 194, 30)
    _logo(pdf, company, 16, 10, 10)
    pdf.set_text_color(*pdf.ink)
    pdf.set_font("DejaVu", size=13)
    pdf.set_xy(31, 11)
    pdf.cell(90, 6, _fit(pdf, company.denomination or "", 88, 13))
    company_lines, _color = _company_lines(pdf, company, 88)
    pdf.set_text_color(*MUTED)
    pdf.set_font("DejaVu", size=7.4)
    y = 18
    for line in company_lines[:3]:
        pdf.set_xy(31, y)
        pdf.cell(88, 4, line)
        y += 4
    pdf.set_text_color(*pdf.ink)
    pdf.set_font("DejaVu", size=20)
    pdf.set_xy(120, 10)
    pdf.cell(74, 8, pdf.kind_title, align="R")
    pdf.set_text_color(*MUTED)
    pdf.set_font("DejaVu", size=7.4)
    pdf.set_xy(120, 19)
    pdf.cell(74, 4, f"N° {document.number}", align="R")
    _meta_block(pdf, document, kind, 120, 24, 74, MUTED, pdf.ink, pdf.line_color)
    client_name, _siren, _address = _client_fields(document)
    _card(
        pdf,
        16,
        36,
        102,
        32,
        KIND_CLIENT_LABELS.get(kind, "FACTURÉ À"),
        client_name,
        _client_lines(pdf, document, 90),
        fill=pdf.soft,
        border=pdf.line_color,
        label_color=pdf.ink,
        name_color=pdf.ink,
    )
    pdf.set_y(74)


def _header_minimal(pdf, company, kind, document):
    pdf.set_draw_color(*pdf.ink)
    pdf.set_line_width(0.5)
    pdf.line(16, 24, 194, 24)
    pdf.set_text_color(*pdf.ink)
    pdf.set_font("DejaVu", size=10)
    pdf.set_xy(16, 10)
    pdf.cell(104, 5, (company.denomination or "").upper())
    pdf.set_font("DejaVu", size=9)
    pdf.set_xy(120, 9)
    pdf.cell(74, 5, pdf.kind_title, align="R")
    pdf.set_text_color(*MUTED)
    pdf.set_font("DejaVu", size=7.4)
    pdf.set_xy(120, 15)
    pdf.cell(74, 4, f"N° {document.number}", align="R")
    _meta_block(pdf, document, kind, 16, 26, 178, MUTED, pdf.ink, pdf.line_color)
    pdf.set_y(38)


def _header_moderne(pdf, company, kind, document):
    pdf.set_fill_color(*pdf.accent)
    pdf.rect(0, 0, 3.2, 120, "F")
    pdf.set_text_color(*pdf.ink)
    pdf.set_font("DejaVu", size=12)
    pdf.set_xy(14, 10)
    pdf.cell(96, 6, _fit(pdf, company.denomination or "", 94, 12))
    company_lines, _color = _company_lines(pdf, company, 94)
    pdf.set_text_color(*MUTED)
    pdf.set_font("DejaVu", size=7.2)
    y = 17
    for line in company_lines[:3]:
        pdf.set_xy(14, y)
        pdf.cell(96, 4, line)
        y += 4
    pdf.set_text_color(*pdf.ink)
    pdf.set_font("DejaVu", size=19)
    pdf.set_xy(116, 9)
    pdf.cell(78, 8, pdf.kind_title, align="R")
    pdf.set_text_color(*MUTED)
    pdf.set_font("DejaVu", size=7.4)
    pdf.set_xy(116, 18)
    pdf.cell(78, 4, f"N° {document.number}", align="R")
    _meta_block(pdf, document, kind, 116, 23, 76, MUTED, pdf.ink, pdf.line_color)
    client_name, _siren, _address = _client_fields(document)
    _card(
        pdf,
        14,
        34,
        96,
        28,
        KIND_CLIENT_LABELS.get(kind, "FACTURÉ À"),
        client_name,
        _client_lines(pdf, document, 84),
        fill=WHITE,
        border=pdf.line_color,
        label_color=pdf.ink,
        name_color=pdf.ink,
    )
    pdf.set_y(66)


def _header_compact(pdf, company, kind, document):
    pdf.set_fill_color(*pdf.ink)
    pdf.rect(0, 0, 210, 3.4, "F")
    pdf.set_fill_color(*pdf.soft)
    pdf.rect(0, 3.4, 210, 26, "F")
    _logo(pdf, company, 16, 8, 9)
    pdf.set_text_color(*pdf.ink)
    pdf.set_font("DejaVu", size=11.5)
    pdf.set_xy(28, 9)
    pdf.cell(80, 5.5, _fit(pdf, company.denomination or "", 78, 11.5))
    company_lines, _color = _company_lines(pdf, company, 80)
    pdf.set_text_color(*MUTED)
    pdf.set_font("DejaVu", size=6.9)
    y = 15
    for line in company_lines[:2]:
        pdf.set_xy(28, y)
        pdf.cell(80, 3.6, line)
        y += 3.6
    pdf.set_text_color(*pdf.accent)
    pdf.set_font("DejaVu", size=14)
    pdf.set_xy(118, 9)
    pdf.cell(76, 6, pdf.kind_title, align="R")
    _meta_block(pdf, document, kind, 118, 16, 76, MUTED, pdf.ink, pdf.line_color)
    pdf.set_y(34)


def _verify_url(document) -> str:
    """Lien public de vérification du document (QR imprimé sur la facture)."""
    from django.conf import settings

    base = (
        getattr(settings, "SITE_BASE_URL", "")
        or "https://rrs-sandy.vercel.app"
    ).rstrip("/")
    return f"{base}/factures/verifier/{document.pk}/"


def _qr_png(url: str) -> bytes:
    import qrcode

    image = qrcode.make(url, box_size=8, border=1)
    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _draw_verify_qr(pdf, document, x, y):
    """Imprime le QR de vérification d'origine (factures émises/déjà créées)."""
    if not getattr(document, "pk", None):
        return
    try:
        png = _qr_png(_verify_url(document))
    except Exception:
        return
    from io import BytesIO

    pdf.set_fill_color(255, 255, 255)
    pdf.set_draw_color(*pdf.line_color)
    pdf.set_line_width(0.2)
    pdf.rect(x - 2, y - 2, 26, 33, "F", round_corners=True, corner_radius=2)
    pdf.image(BytesIO(png), x=x, y=y, w=22)
    pdf.set_text_color(*MUTED)
    pdf.set_font("DejaVu", size=5.2)
    pdf.set_xy(x - 2, y + 24)
    pdf.cell(26, 3, "Vérifier l'origine", align="C")


HEADER_BY_LAYOUT = {
    "royal": _header_royal,
    "emerald": _header_emerald,
    "imperial": _header_imperial,
    "bordeaux": _header_bordeaux,
    "sapphire": _header_sapphire,
    "classique": _header_classique,
    "minimal": _header_minimal,
    "moderne": _header_moderne,
    "compact": _header_compact,
}


def _draw_first_header(pdf, company, kind, document):
    HEADER_BY_LAYOUT.get(pdf.layout, _header_royal)(pdf, company, kind, document)


def _draw_footer_lines(pdf, company):
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


def _draw_totals(pdf, document, kind, rows):
    if pdf.get_y() > 238:
        pdf.add_page()
    box_w = 92
    box_x = 210 - 16 - box_w
    y = max(pdf.get_y() + 8, 22)
    if kind == "invoice" and getattr(document, "pk", None):
        _draw_verify_qr(pdf, document, 16, y + 2)
    pdf.set_fill_color(*pdf.soft)
    pdf.set_draw_color(*pdf.line_color)
    pdf.set_line_width(0.2)
    pdf.rect(box_x, y, box_w, 34, "DF", round_corners=True, corner_radius=3)
    pdf.set_text_color(*pdf.ink)
    pdf.set_font("DejaVu", size=8.5)
    pdf.set_xy(box_x + 5, y + 4)
    pdf.cell(box_w * 0.55, 6, "Sous-total HT")
    pdf.cell(box_w * 0.40, 6, euros(document.amount_ht), align="R")
    row_y = y + 10
    vat_lines = _vat_lines(rows)
    reverse_charge = bool(getattr(document, "reverse_charge", False))
    for rate, amount in vat_lines:
        label = f"TVA {_pct(rate)}"
        if reverse_charge and rate == 0:
            label += " (autoliquidation)"
        pdf.set_xy(box_x + 5, row_y)
        pdf.cell(box_w * 0.55, 6, label)
        pdf.cell(box_w * 0.40, 6, euros(amount), align="R")
        row_y += 6
    if not vat_lines and reverse_charge:
        pdf.set_xy(box_x + 5, row_y)
        pdf.cell(box_w * 0.55, 6, "TVA 0 % (autoliquidation)")
        pdf.cell(box_w * 0.40, 6, euros(Decimal("0.00")), align="R")

    total_y = y + 40
    if pdf.layout == "imperial":
        fill, text = pdf.ink, pdf.accent
        border = pdf.accent
    else:
        fill, text = pdf.ink, WHITE
        border = None
    pdf.set_fill_color(*fill)
    if border:
        pdf.set_draw_color(*border)
        pdf.set_line_width(0.4)
        pdf.rect(
            box_x,
            total_y,
            box_w,
            11,
            "DF",
            round_corners=True,
            corner_radius=2.5,
        )
    else:
        pdf.rect(box_x, total_y, box_w, 11, "F", round_corners=True, corner_radius=2.5)
    pdf.set_text_color(*text)
    pdf.set_font("DejaVu", size=8.5)
    pdf.set_xy(box_x + 5, total_y + 1)
    pdf.cell(box_w * 0.58, 9, "Montant Total TTC (EUR)")
    pdf.set_font("DejaVu", size=10.5)
    pdf.cell(box_w * 0.37, 9, euros(document.amount_ttc), align="R")

    y = total_y + 14
    if kind == "invoice":
        paid = getattr(document, "amount_paid", Decimal("0.00"))
        remaining = getattr(document, "amount_remaining", document.amount_ttc)
        pdf.set_text_color(*pdf.ink)
        pdf.set_font("DejaVu", size=8.5)
        pdf.set_xy(box_x + 5, y)
        pdf.cell(box_w * 0.55, 6, "Montant payé")
        pdf.cell(box_w * 0.40, 6, euros(paid), align="R")
        pdf.set_draw_color(*pdf.accent)
        pdf.set_line_width(0.45)
        pdf.line(box_x + 5, y + 7, box_x + box_w - 5, y + 7)
        pdf.set_text_color(*pdf.accent)
        pdf.set_font("DejaVu", size=10)
        pdf.set_xy(box_x + 5, y + 8)
        pdf.cell(box_w * 0.55, 7, "Montant à payer (EUR)")
        pdf.cell(box_w * 0.40, 7, euros(remaining), align="R")
        y += 18
    else:
        pdf.set_text_color(*pdf.accent)
        pdf.set_font("DejaVu", size=9.5)
        pdf.set_xy(box_x + 5, y)
        label = "Montant à payer (EUR)" if kind == "quote" else "Montant de l'avoir (EUR)"
        pdf.cell(box_w * 0.55, 7, label)
        pdf.cell(box_w * 0.40, 7, euros(document.amount_ttc), align="R")
        y += 10

    note = KIND_NOTES.get(kind, "")
    if note:
        pdf.set_text_color(*MUTED)
        pdf.set_font("DejaVu", size=7.8)
        pdf.set_xy(16, y + 1)
        pdf.cell(92, 4, note)
    return y


def render_document_pdf(document, company, kind: str = "invoice") -> bytes:
    theme = company.invoice_theme if company.invoice_theme in PALETTES else "azur"
    palette = dict(PALETTES[theme])
    layout = (getattr(company, "invoice_layout", "") or "").strip()
    if layout in HEADER_BY_LAYOUT:
        palette["layout"] = layout
    kind_title = KIND_TITLES.get(kind, "FACTURE")
    rows = _line_items(document)
    left = 16
    right = 16
    content_w = 210 - left - right
    columns = _columns(content_w)

    pdf = DocumentPDF(palette, kind_title, left, content_w, columns, document.number)
    pdf.alias_nb_pages()
    pdf.add_font("DejaVu", "", str(FONT))
    pdf.set_font("DejaVu", size=9)
    pdf.add_page()
    _draw_footer_lines(pdf, company)
    _draw_first_header(pdf, company, kind, document)
    pdf._table_header(pdf.get_y())

    desc_w = columns[0][0]
    for index, row in enumerate(rows):
        title_chunks = _wrap(pdf, row["title"] or row["description"] or "", desc_w - 4)
        title_h = max(7.5, 4.5 * len(title_chunks) + 2.8)
        detail_chunks = _wrap(pdf, row["details"], desc_w - 4) if row["details"] else []
        detail_h = max(0, 4.0 * len(detail_chunks) + 1.5)
        row_h = title_h + detail_h
        if pdf.get_y() + row_h > 254:
            pdf.add_page()
        y = pdf.get_y()
        pdf.set_fill_color(*(pdf.soft if index % 2 == 0 else WHITE))
        pdf.rect(left, y, content_w, row_h, "F")
        pdf.set_text_color(*INK)
        pdf.set_font("DejaVu", size=9)
        for chunk_index, chunk in enumerate(title_chunks):
            pdf.set_xy(left + 2, y + 1.5 + chunk_index * 4.5)
            pdf.cell(desc_w - 4, 4.5, chunk)
        if detail_chunks:
            pdf.set_text_color(*MUTED)
            pdf.set_font("DejaVu", size=8.5)
            for chunk_index, chunk in enumerate(detail_chunks):
                pdf.set_xy(left + 2, y + title_h + 1 + chunk_index * 4.0)
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

        pdf.set_draw_color(*pdf.line_color)
        pdf.set_line_width(0.15)
        pdf.line(left, y + row_h, left + content_w, y + row_h)
        pdf.set_y(y + row_h)

    y = _draw_totals(pdf, document, kind, rows)

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
        pdf.set_font("DejaVu", size=6.6)
        pdf.set_xy(left, min(y + 4, 256))
        pdf.multi_cell(content_w - 4, 3.2, "\n".join(legal))

    return bytes(pdf.output())


def render_invoice_pdf(invoice, company) -> bytes:
    return render_document_pdf(invoice, company, kind="invoice")


def render_quote_pdf(quote, company) -> bytes:
    return render_document_pdf(quote, company, kind="quote")


def render_credit_note_pdf(credit_note, company) -> bytes:
    return render_document_pdf(credit_note, company, kind="credit_note")


def first_page_png(payload: bytes, zoom: float = 1.6) -> bytes:
    """Rend la première page du PDF en PNG, pour un aperçu fidèle à l'export."""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        try:
            import pymupdf as fitz
        except ImportError:  # compatibilitéanciennes installations
            import fitz
        document = fitz.open(stream=payload, filetype="pdf")
        try:
            page = document.load_page(0)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            return pixmap.tobytes("png")
        finally:
            document.close()
    document = pdfium.PdfDocument(payload)
    try:
        page = document[0]
        bitmap = page.render(scale=zoom)
        return _pil_to_png(bitmap)
    finally:
        document.close()


def _pil_to_png(bitmap) -> bytes:
    from io import BytesIO

    image = bitmap.to_pil().convert("RGB")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def preview_invoice(company):
    """Document d'exemple pour l'aperçu de la configuration société."""
    now = timezone.now()
    client = SimpleNamespace(
        name="Client Exemple",
        siren="552100554",
        address="8 rue des Lilas, 75011 Paris",
        legal_form="SARL",
        rcs="",
        tva_intra="",
    )
    lines = [
        SimpleNamespace(
            description="Pose de fenêtre",
            product=None,
            quantity=Decimal("1.00"),
            unit_price=Decimal("250.00"),
            vat_rate=Decimal("20.00"),
            amount_ht=Decimal("250.00"),
            amount_ttc=Decimal("300.00"),
        ),
        SimpleNamespace(
            description="Déplacement chantier",
            product=None,
            quantity=Decimal("1.00"),
            unit_price=Decimal("45.00"),
            vat_rate=Decimal("10.00"),
            amount_ht=Decimal("45.00"),
            amount_ttc=Decimal("49.50"),
        ),
    ]
    return SimpleNamespace(
        number="FAC-2026-0042",
        client=client,
        client_name=client.name,
        client_siren=client.siren,
        client_tva_intra="",
        amount_ht=Decimal("295.00"),
        vat_rate=Decimal("20.00"),
        amount_ttc=Decimal("349.50"),
        amount_paid=Decimal("0.00"),
        amount_remaining=Decimal("349.50"),
        reverse_charge=False,
        vat_exemption_reason="",
        created_at=now,
        effective_due_date=(now + timedelta(days=30)).date(),
        lines=lines,
    )


def render_sample_invoice_png(company, zoom: float = 1.6) -> bytes:
    payload = render_document_pdf(preview_invoice(company), company, kind="invoice")
    return first_page_png(payload, zoom=zoom)
