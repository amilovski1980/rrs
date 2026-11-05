"""OCR et heuristiques pour tickets de caisse (reçus)."""
from __future__ import annotations

import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.utils import timezone


class ReceiptOcrError(Exception):
    """Erreur OCR / fichier, message français pour l'utilisateur."""


ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "application/pdf",
}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 Mo

MONEY_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:[ \u00a0]\d{3})*|\d+)([.,]\d{2})\s*€?",
)
TOTAL_TTC_RE = re.compile(
    r"(?:total\s*ttc|montant\s*ttc|net\s*[àa]\s*payer|total\s*[àa]\s*payer|"
    r"total\s*g[eé]n[eé]ral|total\b(?!\s*ht)|ttc)\s*[:\s]*"
    r"(\d{1,3}(?:[ \u00a0]\d{3})*|\d+)([.,]\d{2})",
    re.IGNORECASE,
)
TOTAL_HT_RE = re.compile(
    r"(?:total\s*ht|montant\s*ht|ht)\s*[:\s]*"
    r"(\d{1,3}(?:[ \u00a0]\d{3})*|\d+)([.,]\d{2})",
    re.IGNORECASE,
)
TVA_AMOUNT_RE = re.compile(
    r"(?:montant\s*)?TVA\s*(?:\d{1,2}(?:[.,]\d{1,2})?\s*%)?\s*[:\s]*"
    r"(\d{1,3}(?:[ \u00a0]\d{3})*|\d+)([.,]\d{2})",
    re.IGNORECASE,
)
VAT_RATE_RE = re.compile(
    r"(?:TVA|VAT)\s*(?:à\s*)?(\d{1,2}(?:[.,]\d{1,2})?)\s*%",
    re.IGNORECASE,
)
DATE_RE = re.compile(
    r"\b(\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}|\d{4}-\d{2}-\d{2})\b"
)
PAYMENT_RE = re.compile(
    r"\b(CB|carte\s*bancaire|carte\s*bleue|visa|mastercard|esp[eè]ces|"
    r"liquide|esp[eè]ce|ch[eè]que|virement|sans\s*contact|contactless|"
    r"apple\s*pay|google\s*pay)\b",
    re.IGNORECASE,
)
STORE_SKIP = re.compile(
    r"^(ticket|caisse|merci|tva|total|ht|ttc|date|heure|tel|www\.|http|"
    r"siret|siren|rcs|capital|eur|€|\d+$)",
    re.IGNORECASE,
)
CATEGORY_KEYWORDS = {
    "carburant": ("carburant", "essence", "gazole", "diesel", "station", "total energies", "bp ", "shell", "esso"),
    "restauration": ("restaurant", "resto", "café", "cafe", "boulangerie", "snack", "mcdo", "burger", "pizza"),
    "fournitures": ("fourniture", "bricolage", "leroy", "castorama", "bureau", "papeterie", "amazon"),
    "transport": ("sncf", "ratp", "uber", "taxi", "péage", "peage", "parking", "autolib"),
    "deplacement": ("hôtel", "hotel", "airbnb", "booking", "train", "vol ", "avion"),
}


def _money(raw_int: str, raw_dec: str) -> Decimal:
    whole = raw_int.replace(" ", "").replace("\u00a0", "")
    cents = raw_dec.lstrip(".,")
    return Decimal(f"{whole}.{cents}").quantize(Decimal("0.01"))


def _parse_decimal(value: str) -> Decimal:
    cleaned = str(value).replace(" ", "").replace("\u00a0", "").replace(",", ".")
    return Decimal(cleaned).quantize(Decimal("0.01"))


def validate_upload(filename: str, content_type: str | None, size: int) -> None:
    if size <= 0:
        raise ReceiptOcrError("Le fichier est vide.")
    if size > MAX_UPLOAD_BYTES:
        raise ReceiptOcrError(
            "Fichier trop volumineux (maximum 8 Mo). Compressez l'image ou le PDF."
        )
    name = (filename or "").lower()
    ext = ""
    if "." in name:
        ext = "." + name.rsplit(".", 1)[-1]
    ctype = (content_type or "").split(";")[0].strip().lower()
    ok_ext = ext in ALLOWED_EXTENSIONS
    ok_type = ctype in ALLOWED_IMAGE_TYPES or ctype in ("application/octet-stream", "")
    if not ok_ext and not (ctype in ALLOWED_IMAGE_TYPES):
        raise ReceiptOcrError(
            "Type de fichier non pris en charge. Envoyez un JPG, PNG, WEBP ou PDF."
        )
    if not ok_ext and not ok_type:
        raise ReceiptOcrError(
            "Type de fichier non pris en charge. Envoyez un JPG, PNG, WEBP ou PDF."
        )


def preprocess_receipt_image(image):
    """Niveaux de gris, agrandissement, seuil — adapté aux tickets étroits."""
    from PIL import Image, ImageOps, ImageFilter

    img = image.convert("L")
    w, h = img.size
    # Agrandir les petits tickets pour le OCR
    if w < 900:
        scale = max(2, int(900 / max(w, 1)))
        img = img.resize((w * scale, h * scale))
    img = ImageOps.autocontrast(img)
    img = img.filter(ImageFilter.MedianFilter(size=3))
    # Seuil simple
    img = img.point(lambda x: 255 if x > 160 else 0)
    return img


def _tesseract_available() -> bool:
    try:
        import pytesseract
        from pytesseract import TesseractNotFoundError
    except ImportError:
        return False
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def ocr_image_bytes(data: bytes, filename: str = "") -> str:
    """OCR image (jpg/png/webp). Dégradation claire si moteur absent."""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise ReceiptOcrError(
            "Le traitement d'image n'est pas disponible (Pillow manquant)."
        ) from exc
    try:
        import pytesseract
    except ImportError as exc:
        raise ReceiptOcrError(
            "Le moteur OCR n'est pas installé (pytesseract). "
            "Saisissez le ticket manuellement ou installez Tesseract."
        ) from exc

    if not _tesseract_available():
        raise ReceiptOcrError(
            "Le moteur OCR Tesseract est introuvable sur le serveur. "
            "Saisissez le ticket manuellement, ou installez le binaire tesseract "
            "(langues fra+eng)."
        )

    try:
        image = Image.open(io.BytesIO(data))
    except Exception as exc:
        raise ReceiptOcrError(
            "Image illisible. Vérifiez que le fichier n'est pas corrompu."
        ) from exc

    processed = preprocess_receipt_image(image)
    try:
        text = pytesseract.image_to_string(processed, lang="fra+eng")
    except Exception as exc:
        # Retry english-only if fra missing
        try:
            text = pytesseract.image_to_string(processed, lang="eng")
        except Exception as exc2:
            raise ReceiptOcrError(
                "Échec de l'OCR sur cette image. Essayez une photo plus nette "
                "ou saisissez le ticket à la main."
            ) from exc2

    text = (text or "").strip()
    if not text:
        raise ReceiptOcrError(
            "Aucun texte détecté sur ce ticket. Photo floue, trop sombre, "
            "ou ticket vide — réessayez ou saisissez manuellement."
        )
    return text


def extract_pdf_text_or_ocr(data: bytes) -> str:
    """PDF : texte natif d'abord ; sinon message orientant vers une image."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise ReceiptOcrError(
            "La lecture PDF n'est pas disponible (pypdf manquant)."
        ) from exc
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise ReceiptOcrError("Impossible de lire ce fichier PDF.") from exc
    chunks = []
    for page in reader.pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:
            continue
    text = "\n".join(chunks).strip()
    if text:
        return text
    raise ReceiptOcrError(
        "Ce PDF ne contient pas de texte sélectionnable (probablement un scan). "
        "Exportez-le en JPG ou PNG, puis réimportez-le pour l'OCR."
    )


def extract_receipt_text(data: bytes, filename: str = "", content_type: str = "") -> str:
    name = (filename or "").lower()
    ctype = (content_type or "").lower()
    if name.endswith(".pdf") or "pdf" in ctype:
        return extract_pdf_text_or_ocr(data)
    return ocr_image_bytes(data, filename=filename)


def _parse_date(raw: str) -> date | None:
    raw = raw.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def guess_category(text: str, store: str) -> str:
    blob = f"{store} {text}".lower()
    for cat, words in CATEGORY_KEYWORDS.items():
        if any(w in blob for w in words):
            return cat
    return "autre"


def parse_receipt_text(text: str) -> dict[str, Any]:
    """Heuristiques pour magasin, date, TTC, TVA, paiement, lignes."""
    today = timezone.localdate()
    data: dict[str, Any] = {
        "magasin": "",
        "date": today,
        "montant_ttc": None,
        "montant_tva": None,
        "taux_tva": Decimal("20.00"),
        "moyen_paiement": "",
        "categorie": "autre",
        "line_items": [],
        "raw_excerpt": (text or "")[:3000],
    }
    if not text or not text.strip():
        return data

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines[:8]:
        if STORE_SKIP.search(ln):
            continue
        if MONEY_RE.search(ln) and len(ln) < 12:
            continue
        if re.search(r"[A-Za-zÀ-ÿ]{3,}", ln):
            data["magasin"] = ln[:200]
            break

    for m in DATE_RE.finditer(text):
        parsed = _parse_date(m.group(1))
        if parsed:
            data["date"] = parsed
            break

    ttc_m = TOTAL_TTC_RE.search(text)
    if ttc_m:
        try:
            data["montant_ttc"] = _money(ttc_m.group(1), ttc_m.group(2))
        except (InvalidOperation, ValueError):
            pass
    if data["montant_ttc"] is None:
        # Dernier montant « gros » plausible
        amounts = []
        for m in MONEY_RE.finditer(text):
            try:
                amounts.append(_money(m.group(1), m.group(2)))
            except (InvalidOperation, ValueError):
                continue
        if amounts:
            data["montant_ttc"] = max(amounts)

    vat_m = VAT_RATE_RE.search(text)
    if vat_m:
        try:
            data["taux_tva"] = _parse_decimal(vat_m.group(1))
        except InvalidOperation:
            pass

    tva_m = TVA_AMOUNT_RE.search(text)
    if tva_m:
        try:
            data["montant_tva"] = _money(tva_m.group(1), tva_m.group(2))
        except (InvalidOperation, ValueError):
            pass

    if data["montant_tva"] is None and data["montant_ttc"] is not None and data["taux_tva"] is not None:
        rate = data["taux_tva"]
        if rate > 0:
            ht = (data["montant_ttc"] / (Decimal("1") + rate / Decimal("100"))).quantize(Decimal("0.01"))
            data["montant_tva"] = (data["montant_ttc"] - ht).quantize(Decimal("0.01"))
        else:
            data["montant_tva"] = Decimal("0.00")

    pay_m = PAYMENT_RE.search(text)
    if pay_m:
        data["moyen_paiement"] = pay_m.group(1).strip()[:40]

    data["categorie"] = guess_category(text, data["magasin"])

    # Lignes simples : description + montant en fin de ligne
    line_re = re.compile(
        r"^(.{2,60}?)\s+(\d{1,3}(?:[ \u00a0]\d{3})*|\d+)([.,]\d{2})\s*€?$"
    )
    for ln in lines:
        low = ln.lower()
        if any(k in low for k in ("total", "tva", "ht", "ttc", "net à payer", "merci")):
            continue
        m = line_re.match(ln)
        if not m:
            continue
        desc = m.group(1).strip()
        if STORE_SKIP.search(desc):
            continue
        try:
            data["line_items"].append(
                {"description": desc[:200], "montant": str(_money(m.group(2), m.group(3)))}
            )
        except (InvalidOperation, ValueError):
            continue
        if len(data["line_items"]) >= 30:
            break

    return data
