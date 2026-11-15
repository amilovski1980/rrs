"""OCR du ticket. Le moteur Tesseract n'est pas indispensable : l'agent IA
(multimodal, même configuration que le chat) transcrit l'image en texte."""
from __future__ import annotations

import base64
import io
import logging
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.utils import timezone

logger = logging.getLogger(__name__)


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
MAX_UPLOAD_BYTES = 4 * 1024 * 1024  # 4 Mo : limite de requête Vercel inclus

MONEY_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:[ \u00a0]\d{3})*|\d+)([.,]\d{2})\s*€?",
)
TOTAL_TTC_RE = re.compile(
    r"(?<!sous[- ])(?:total\s*ttc|montant\s*ttc|net\s*[àa]\s*payer|"
    r"total\s*[àa]\s*payer|montant\s*d[uû]|total\s*g[eé]n[eé]ral|"
    r"total\s*(?:carte|esp[eè]ces|pay[eé])|total\b(?!\s*ht)|ttc)\s*[:\s]*"
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
VAT_LINE_RE = re.compile(
    r"(?:TVA|VAT)\s*(?:à\s*)?(\d{1,2}(?:[.,]\d{1,2})?)\s*%"
    r"[^\d\n]{0,24}"
    r"(\d{1,3}(?:[ \u00a0]\d{3})*|\d+)([.,]\d{2})",
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
            "Fichier trop volumineux (maximum 4 Mo par requête du serveur). "
            "Reprenez la photo en résolution plus basse, ou compressez l'image."
        )
    name = (filename or "").lower()
    ext = ""
    if "." in name:
        ext = "." + name.rsplit(".", 1)[-1]
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ext in {".heic", ".heif"} or "heic" in ctype or "heif" in ctype:
        raise ReceiptOcrError(
            "Le format HEIC/HEIF n'est pas pris en charge. "
            "Dans Réglages → Appareil photo, choisissez « Compatible au maximum » "
            "(JPG), ou exportez la photo en JPG/PNG avant l'envoi."
        )
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



def prepare_image_bytes_for_ocr(data: bytes, filename: str = "") -> bytes:
    """Réduit les photos téléphone trop lourdes avant OCR (max ~2000 px, JPEG)."""
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return data
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return data
    try:
        image = Image.open(io.BytesIO(data))
    except Exception:
        return data
    image = ImageOps.exif_transpose(image)
    # HEIC peut s'ouvrir avec un plugin rare ; si format inconnu on laisse validate_upload
    fmt = (image.format or "").upper()
    if fmt in {"HEIC", "HEIF"}:
        raise ReceiptOcrError(
            "Le format HEIC/HEIF n'est pas pris en charge. "
            "Enregistrez la photo en JPG ou PNG."
        )
    max_side = 2000
    w, h = image.size
    if max(w, h) > max_side:
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    elif image.mode == "L":
        image = image.convert("RGB")
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=85, optimize=True)
    return out.getvalue()


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

    if not _tesseract_available():
        # L'agent IA (modèle multimodal du chat) remplace le binaire OCR :
        # même pipeline texte, aucun binaire système à installer.
        return transcribe_with_agent(data, filename=filename)

    try:
        import pytesseract
    except ImportError as exc:
        raise ReceiptOcrError(
            "Le moteur OCR n'est pas installé (pytesseract). "
            "Saisissez le ticket manuellement ou installez Tesseract."
        ) from exc

    try:
        data = prepare_image_bytes_for_ocr(data, filename=filename)
        image = Image.open(io.BytesIO(data))
    except ReceiptOcrError:
        raise
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


_TRANSCRIBE_PROMPT = (
    "Transcris fidèlement TOUT le texte de cette photo de ticket de caisse ou de "
    "document comptable, ligne par ligne, dans l'ordre visuel du haut vers le bas. "
    "Copie les montants tels qu'ils apparaissent (espaces des milliers, devise). "
    "N'ajoute AUCUN commentaire, titre ou interprétation : renvoie uniquement la "
    "transcription."
)

_VISION_TIMEOUT_SECONDS = 45


def _vision_candidates():
    """Fournisseurs à essayer, par ordre de pertinence pour l'analyse d'image.

    L'agent configuré pour le chat d'abord ; puis xAI (clé vocale/vision)
    qui embarque toujours un modèle multimodal.
    """
    from ai.providers import text_provider

    candidates: list[dict] = []
    try:
        provider = text_provider()
    except Exception:
        provider = None
    if provider and provider.get("configured"):
        candidates.append(provider)

    from django.conf import settings

    xai_key = (getattr(settings, "XAI_API_KEY", "") or "").strip()
    if xai_key and all(c.get("key") != xai_key for c in candidates):
        candidates.append({
            "code": "xai-vision",
            "label": "xAI (vision)",
            "base": "https://api.x.ai/v1",
            "key": xai_key,
            "model": getattr(settings, "XAI_VISION_MODEL", "") or _XAI_VISION_MODEL_FALLBACKS[0],
            "configured": True,
        })
    return candidates


_XAI_VISION_MODEL_FALLBACKS = (
    "grok-2-vision-1212",
    "grok-4-vision",
    "grok-vision-1212",
)


def _vision_call(candidate: dict, image_data: bytes) -> str:
    encoded = base64.b64encode(image_data).decode("ascii")
    payload = {
        "model": candidate["model"],
        "temperature": 0,
        "max_tokens": 1400,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64," + encoded},
                    },
                    {"type": "text", "text": _TRANSCRIBE_PROMPT},
                ],
            }
        ],
    }
    try:
        import httpx

        response = httpx.post(
            candidate["base"].rstrip("/") + "/chat/completions",
            json=payload,
            headers={
                "Authorization": "Bearer " + (candidate["key"] or ""),
                "Content-Type": "application/json",
            },
            timeout=_VISION_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.warning(
            "Transcription vision : fournisseur %s injoignable (%s)",
            candidate.get("code"), exc.__class__.__name__,
        )
        raise ReceiptOcrError(
            f"{candidate.get('label') or candidate.get('model')} : injoignable depuis le serveur "
            f"({exc.__class__.__name__})."
        )
    if response.status_code == 429:
        raise ReceiptOcrError(
            "L'agent IA est momentanément saturé (limite de débit). "
            "Réessayez dans une minute."
        )
    if response.status_code >= 400:
        detail = ""
        try:
            payload_error = response.json().get("error", {})
            detail = str(payload_error.get("msg") or payload_error.get("message") or "")[:160]
        except Exception:
            detail = ""
        logger.warning(
            "Transcription vision : fournisseur %s HTTP %s %s",
            candidate.get("code"), response.status_code, detail,
        )
        raise ReceiptOcrError(
            f"{candidate.get('label') or candidate.get('model')} : refus de lecture "
            f"(HTTP {response.status_code}){(' — ' + detail) if detail else ''}."
        )
    try:
        text = response.json()["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, ValueError):
        text = ""
    text = str(text).strip()
    if not text:
        raise ReceiptOcrError(
            "L'agent IA n'a rien transcrit. Essayez une photo plus nette "
            "ou saisissez le ticket à la main."
        )
    return text


def transcribe_with_agent(data: bytes, filename: str = "") -> str:
    """Transcription de l'image par l'agent IA (modèle multimodal du chat).

    Utilisé quand Tesseract est absent (déploiement serverless) : la lecture
    passe par l'agent, pas par un binaire OCR système.
    """
    candidates = _vision_candidates()

    # xAI : plusieurs modèles vision en cascade si l'un est absent (404).
    extended = []
    for candidate in candidates:
        extended.append(candidate)
        if candidate.get("code") == "xai-vision":
            for fallback_model in _XAI_VISION_MODEL_FALLBACKS[1:]:
                alternative = dict(candidate, model=fallback_model)
                extended.append(alternative)
    if not extended:
        raise ReceiptOcrError(
            "Aucun moteur d'analyse disponible : Tesseract est absent du serveur "
            "et l'agent IA n'est pas configuré. Configurez l'agent Aminia "
            "(Configuration → Aminia) ou saisissez le ticket manuellement."
        )

    try:
        image_data = prepare_image_bytes_for_ocr(data, filename=filename)
    except ReceiptOcrError:
        raise
    except Exception:
        image_data = data

    failures: list[str] = []
    for candidate in extended:
        try:
            return _vision_call(candidate, image_data)
        except ReceiptOcrError as exc:
            failures.append(str(exc))
            if "saturé" in str(exc):
                raise
    raise ReceiptOcrError(
        "L'analyse par l'agent IA a échoué sur tous les fournisseurs essayés ("
        + " ; ".join(failures)
        + "). Ollama auto-hébergé doit être accessible publiquement depuis le "
        "serveur (ou utilisez Ollama Cloud), et le modèle doit savoir lire les images."
    )


def _pdf_page_images(reader) -> list[tuple[str, bytes]]:
    """Images incorporées dans un PDF (souvent une page scannée = une image)."""
    images: list[tuple[str, bytes]] = []
    for page in reader.pages:
        try:
            page_images = list(page.images)
        except Exception:
            continue
        for image in page_images[:4]:
            data = getattr(image, "data", b"") or b""
            if data:
                images.append((getattr(image, "name", "") or "page.jpg", data))
        if len(images) >= 8:
            break
    return images


def _ocr_pdf_images(reader) -> str:
    chunks = []
    last_error: ReceiptOcrError | None = None
    for name, data in _pdf_page_images(reader):
        try:
            text = ocr_image_bytes(data, filename=name)
        except ReceiptOcrError as exc:
            last_error = exc
            continue
        if text:
            chunks.append(text)
    if chunks:
        return "\n".join(chunks).strip()
    if last_error is not None:
        raise last_error
    return ""


def extract_pdf_text_or_ocr(data: bytes) -> str:
    """PDF : texte natif, puis OCR des images incorporées pour les scans."""
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
    # Un PDF scanné peut contenir quelques caractères d'en-tête sans le corps.
    if len(text) >= 40:
        return text
    ocr_error: ReceiptOcrError | None = None
    try:
        ocr_text = _ocr_pdf_images(reader)
    except ReceiptOcrError as exc:
        ocr_text = ""
        ocr_error = exc
    combined = "\n".join(part for part in (text, ocr_text) if part).strip()
    if combined:
        return combined
    if ocr_error is not None:
        raise ReceiptOcrError(
            "Ce PDF est un scan sans texte sélectionnable. " + str(ocr_error)
        )
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
        "vat_breakdown": [],
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

    vat_lines = []
    for vat_m in VAT_LINE_RE.finditer(text):
        try:
            rate = _parse_decimal(vat_m.group(1))
            amount = _money(vat_m.group(2), vat_m.group(3))
        except (InvalidOperation, ValueError):
            continue
        if rate > 30 or amount > Decimal("10000.00"):
            continue
        vat_lines.append({"taux": rate, "montant": amount})
    if vat_lines:
        data["vat_breakdown"] = [
            {"taux": str(item["taux"]), "montant": str(item["montant"])}
            for item in vat_lines
        ]
        data["montant_tva"] = sum(
            (item["montant"] for item in vat_lines), Decimal("0.00")
        ).quantize(Decimal("0.01"))
        # Le taux principal est celui qui porte le plus de TVA.
        data["taux_tva"] = max(vat_lines, key=lambda item: item["montant"])["taux"]
    else:
        vat_m = VAT_RATE_RE.search(text)
        if vat_m:
            try:
                data["taux_tva"] = _parse_decimal(vat_m.group(1))
            except InvalidOperation:
                pass
        vat_amounts = []
        for tva_m in TVA_AMOUNT_RE.finditer(text):
            try:
                vat_amounts.append(_money(tva_m.group(1), tva_m.group(2)))
            except (InvalidOperation, ValueError):
                continue
        if vat_amounts:
            data["montant_tva"] = sum(vat_amounts, Decimal("0.00")).quantize(Decimal("0.01"))

    if data["montant_ttc"] is not None and data["montant_tva"] is not None:
        # Une TVA supérieure au TTC signale une lecture aberrante.
        if data["montant_tva"] > data["montant_ttc"]:
            data["montant_tva"] = None
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
