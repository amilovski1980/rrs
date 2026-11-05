"""Import de facture PDF : extraction texte + heuristiques, IA optionnelle."""
from __future__ import annotations

import re
import uuid
from decimal import Decimal, InvalidOperation
from io import BytesIO

from django.conf import settings
from django.db import transaction

from .models import Client, Invoice, InvoiceLine, Product


class PdfImportError(Exception):
    """Erreur métier d'import PDF, message destiné à l'utilisateur (FR)."""


MONEY_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:[ \u00a0]\d{3})*|\d+)([.,]\d{2})\s*€?",
    re.IGNORECASE,
)
SIREN_RE = re.compile(r"\bSIREN\s*[:\s]?\s*(\d{3}\s?\d{3}\s?\d{3})\b", re.IGNORECASE)
SIREN_BARE_RE = re.compile(r"\b(\d{9})\b")
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
INVOICE_NUM_RE = re.compile(
    r"(?:facture|n[°o]|num(?:éro|ero)?)\s*[:\s#]?\s*([A-Z0-9][A-Z0-9\-/]{3,})",
    re.IGNORECASE,
)
DATE_RE = re.compile(
    r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b"
)
VAT_RE = re.compile(r"(?:TVA|VAT)\s*(?:à\s*)?(\d{1,2}(?:[.,]\d{1,2})?)\s*%", re.IGNORECASE)
CLIENT_RE = re.compile(
    r"(?:factur[ée]\s*[àa]|client|destinataire)\s*[:\s]+(.+)",
    re.IGNORECASE,
)
TOTAL_HT_RE = re.compile(
    r"(?:total\s*ht|montant\s*ht|ht)\s*[:\s]*"
    r"(\d{1,3}(?:[ \u00a0]\d{3})*|\d+)([.,]\d{2})",
    re.IGNORECASE,
)
TOTAL_TTC_RE = re.compile(
    r"(?:total\s*ttc|net\s*[àa]\s*payer|ttc)\s*[:\s]*"
    r"(\d{1,3}(?:[ \u00a0]\d{3})*|\d+)([.,]\d{2})",
    re.IGNORECASE,
)
LINE_RE = re.compile(
    r"^(.+?)\s+(\d+(?:[.,]\d+)?)\s+[x×*]\s+"
    r"(\d+(?:[.,]\d{1,2})?)\s+(?:€\s*)?(?:TVA\s*)?"
    r"(\d+(?:[.,]\d+)?)\s*%?",
    re.IGNORECASE | re.MULTILINE,
)
SIMPLE_LINE_RE = re.compile(
    r"^(.{3,80}?)\s+(\d+(?:[.,]\d{1,2})?)\s*€?\s+(\d+(?:[.,]\d{1,2})?)\s*%",
    re.MULTILINE,
)


def _money(raw_int: str, raw_dec: str) -> Decimal:
    whole = raw_int.replace(" ", "").replace("\u00a0", "")
    cents = raw_dec.lstrip(".,")
    return Decimal(f"{whole}.{cents}").quantize(Decimal("0.01"))


def _parse_decimal(value: str) -> Decimal:
    cleaned = str(value).replace(" ", "").replace("\u00a0", "").replace(",", ".")
    return Decimal(cleaned).quantize(Decimal("0.01"))


def extract_pdf_text(data: bytes) -> str:
    """Extrait le texte d'un PDF. Lève PdfImportError si aucun texte."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise PdfImportError(
            "La bibliothèque d'extraction PDF n'est pas installée (pypdf)."
        ) from exc

    try:
        reader = PdfReader(BytesIO(data))
    except Exception as exc:
        raise PdfImportError("Impossible de lire ce fichier PDF.") from exc

    chunks = []
    for page in reader.pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:
            continue
    text = "\n".join(chunks).strip()
    if not text:
        raise PdfImportError(
            "Aucun texte extractible : le PDF semble scanné ou protégé. "
            "Utilisez un PDF avec texte sélectionnable."
        )
    return text


def parse_invoice_text(text: str) -> dict:
    """Heuristiques déterministes pour extraire les champs d'une facture."""
    data = {
        "client_name": "",
        "client_siren": "",
        "client_email": "",
        "client_address": "",
        "invoice_number": "",
        "invoice_date": "",
        "amount_ht": None,
        "vat_rate": None,
        "amount_ttc": None,
        "lines": [],
        "raw_excerpt": text[:2000],
    }

    m = CLIENT_RE.search(text)
    if m:
        data["client_name"] = m.group(1).strip().split("\n")[0][:200]
    if not data["client_name"]:
        for line in text.splitlines():
            line = line.strip()
            if line.lower().startswith("facturé à") or line.lower().startswith("facture a"):
                continue
            if len(line) >= 3 and not line.lower().startswith("siren") and "€" not in line:
                # Première ligne « nom » plausible après en-tête
                if re.search(r"[A-Za-zÀ-ÿ]{3,}", line):
                    data["client_name"] = line[:200]
                    break

    siren_m = SIREN_RE.search(text)
    if siren_m:
        data["client_siren"] = re.sub(r"\D", "", siren_m.group(1))
    email_m = EMAIL_RE.search(text)
    if email_m:
        data["client_email"] = email_m.group(0)[:200]

    num_m = INVOICE_NUM_RE.search(text)
    if num_m:
        data["invoice_number"] = num_m.group(1)[:30]

    date_m = DATE_RE.search(text)
    if date_m:
        data["invoice_date"] = date_m.group(1)

    vat_m = VAT_RE.search(text)
    if vat_m:
        try:
            data["vat_rate"] = _parse_decimal(vat_m.group(1))
        except InvalidOperation:
            pass

    ht_m = TOTAL_HT_RE.search(text)
    if ht_m:
        try:
            data["amount_ht"] = _money(ht_m.group(1), ht_m.group(2))
        except (InvalidOperation, ValueError):
            pass
    ttc_m = TOTAL_TTC_RE.search(text)
    if ttc_m:
        try:
            data["amount_ttc"] = _money(ttc_m.group(1), ttc_m.group(2))
        except (InvalidOperation, ValueError):
            pass

    for match in LINE_RE.finditer(text):
        try:
            data["lines"].append(
                {
                    "description": match.group(1).strip()[:255],
                    "quantity": _parse_decimal(match.group(2)),
                    "unit_price": _parse_decimal(match.group(3)),
                    "vat_rate": _parse_decimal(match.group(4)),
                }
            )
        except (InvalidOperation, ValueError):
            continue
    if not data["lines"]:
        for match in SIMPLE_LINE_RE.finditer(text):
            desc = match.group(1).strip()
            if desc.lower() in ("désignation", "designation", "total", "ht", "ttc"):
                continue
            try:
                data["lines"].append(
                    {
                        "description": desc[:255],
                        "quantity": Decimal("1.00"),
                        "unit_price": _parse_decimal(match.group(2)),
                        "vat_rate": _parse_decimal(match.group(3)),
                    }
                )
            except (InvalidOperation, ValueError):
                continue

    if data["amount_ht"] is None and data["lines"]:
        data["amount_ht"] = sum(
            (line["quantity"] * line["unit_price"] for line in data["lines"]),
            Decimal("0.00"),
        ).quantize(Decimal("0.01"))
    if data["vat_rate"] is None and data["lines"]:
        data["vat_rate"] = data["lines"][0]["vat_rate"]
    if data["vat_rate"] is None:
        data["vat_rate"] = Decimal("20.00")
    if data["amount_ht"] is None and data["amount_ttc"] is not None:
        rate = data["vat_rate"] or Decimal("0")
        data["amount_ht"] = (
            data["amount_ttc"] / (Decimal("1") + rate / Decimal("100"))
        ).quantize(Decimal("0.01"))

    return data


def enhance_with_ai(text: str, parsed: dict) -> dict:
    """Enrichit le parse via Qwen si configuré ; sinon renvoie parsed tel quel."""
    base = getattr(settings, "LLM_BASE_URL", "") or ""
    # Pas d'appel réseau si l'URL pointe vers localhost non joignable en tests :
    # on tente seulement si LLM_API_KEY est non vide ET pas la valeur placeholder.
    api_key = getattr(settings, "LLM_API_KEY", "") or ""
    if not api_key or api_key in ("not-needed-for-vllm-local", "test-disabled"):
        return parsed
    try:
        from ai.qwen import QwenClient

        client = QwenClient()
        prompt = (
            "Extrais en JSON les champs client_name, client_siren, client_email, "
            "client_address, invoice_number, amount_ht, vat_rate, amount_ttc, "
            "et lines[{description,quantity,unit_price,vat_rate}] de cette facture. "
            "Réponds uniquement avec un objet JSON.\n\n"
            + text[:6000]
        )
        response = client.chat(
            [{"role": "user", "content": prompt}],
        )
        content = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        import json

        # Strip éventuelles fences markdown
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
        payload = json.loads(content)
        if not isinstance(payload, dict):
            return parsed
        for key in (
            "client_name",
            "client_siren",
            "client_email",
            "client_address",
            "invoice_number",
        ):
            if payload.get(key) and not parsed.get(key):
                parsed[key] = str(payload[key])[:255]
        for key in ("amount_ht", "vat_rate", "amount_ttc"):
            if payload.get(key) is not None and parsed.get(key) is None:
                try:
                    parsed[key] = _parse_decimal(str(payload[key]))
                except (InvalidOperation, ValueError):
                    pass
        if payload.get("lines") and not parsed.get("lines"):
            lines = []
            for raw in payload["lines"]:
                try:
                    lines.append(
                        {
                            "description": str(raw.get("description") or "Prestation")[:255],
                            "quantity": _parse_decimal(str(raw.get("quantity") or "1")),
                            "unit_price": _parse_decimal(str(raw.get("unit_price") or "0")),
                            "vat_rate": _parse_decimal(str(raw.get("vat_rate") or "20")),
                        }
                    )
                except (InvalidOperation, ValueError, TypeError):
                    continue
            if lines:
                parsed["lines"] = lines
    except Exception:
        # Jamais bloquant : repli sur le parse déterministe.
        return parsed
    return parsed


def find_or_create_client(company, parsed: dict) -> Client:
    siren = re.sub(r"\D", "", parsed.get("client_siren") or "")
    email = (parsed.get("client_email") or "").strip().lower()
    name = (parsed.get("client_name") or "").strip()
    qs = Client.objects.filter(company=company)
    client = None
    if siren and len(siren) == 9:
        client = qs.filter(siren=siren).first()
    if client is None and email:
        client = qs.filter(email__iexact=email).first()
    if client is None and name:
        client = qs.filter(name__iexact=name).first()
    if client is None:
        if not name:
            name = "Client importé"
        client = Client.objects.create(
            company=company,
            name=name[:200],
            siren=siren if len(siren) == 9 else "",
            email=email[:200] if email else "",
            address=(parsed.get("client_address") or "")[:255],
        )
    else:
        updated = []
        if siren and len(siren) == 9 and not client.siren:
            client.siren = siren
            updated.append("siren")
        if email and not client.email:
            client.email = email[:200]
            updated.append("email")
        addr = (parsed.get("client_address") or "").strip()
        if addr and not client.address:
            client.address = addr[:255]
            updated.append("address")
        if updated:
            client.save(update_fields=updated + ["updated_at"])
    return client


def find_or_create_product(company, line: dict) -> Product:
    label = (line.get("description") or "Prestation")[:200]
    existing = Product.objects.filter(company=company, label__iexact=label).first()
    if existing:
        return existing
    return Product.objects.create(
        company=company,
        label=label,
        description=label,
        unit_price=line.get("unit_price") or Decimal("0.00"),
        vat_rate=line.get("vat_rate") or Decimal("20.00"),
    )


def create_draft_invoice_from_parsed(company, parsed: dict, source_name: str = "") -> Invoice:
    """Crée client + produits + facture brouillon (sans consommer de numéro FAC)."""
    if not parsed.get("amount_ht") and not parsed.get("lines"):
        raise PdfImportError(
            "Impossible d'interpréter les montants de cette facture. "
            "Vérifiez que le PDF contient un total HT ou des lignes détaillées."
        )
    amount_ht = parsed.get("amount_ht")
    vat_rate = parsed.get("vat_rate") or Decimal("20.00")
    if amount_ht is None:
        amount_ht = sum(
            (
                (line.get("quantity") or Decimal("1"))
                * (line.get("unit_price") or Decimal("0"))
                for line in parsed.get("lines") or []
            ),
            Decimal("0.00"),
        ).quantize(Decimal("0.01"))
    if amount_ht <= 0:
        raise PdfImportError("Le montant HT extrait est invalide ou nul.")

    with transaction.atomic():
        client = find_or_create_client(company, parsed)
        invoice = Invoice.objects.create(
            company=company,
            number=f"BR-{uuid.uuid4().hex[:10]}",
            client=client,
            client_name=client.name,
            client_siren=client.siren,
            amount_ht=amount_ht,
            vat_rate=vat_rate,
            status="draft",
        )
        lines = parsed.get("lines") or []
        if not lines:
            product = find_or_create_product(
                company,
                {
                    "description": source_name or "Prestation importée",
                    "unit_price": amount_ht,
                    "vat_rate": vat_rate,
                },
            )
            InvoiceLine.objects.create(
                invoice=invoice,
                product=product,
                description=product.label,
                quantity=Decimal("1.000"),
                unit_price=amount_ht,
                vat_rate=vat_rate,
                position=0,
            )
        else:
            for idx, line in enumerate(lines):
                product = find_or_create_product(company, line)
                InvoiceLine.objects.create(
                    invoice=invoice,
                    product=product,
                    description=(line.get("description") or product.label)[:255],
                    quantity=line.get("quantity") or Decimal("1.000"),
                    unit_price=line.get("unit_price") or Decimal("0.00"),
                    vat_rate=line.get("vat_rate") or vat_rate,
                    position=idx,
                )
    return invoice


def import_invoice_pdf(company, data: bytes, filename: str = "") -> tuple[Invoice, dict]:
    """Pipeline complet : texte → parse → IA optionnelle → brouillon."""
    text = extract_pdf_text(data)
    parsed = parse_invoice_text(text)
    parsed = enhance_with_ai(text, parsed)
    if not parsed.get("client_name"):
        # Dernier recours : première ligne alphabétique
        for line in text.splitlines():
            candidate = line.strip()
            if len(candidate) >= 3 and re.search(r"[A-Za-zÀ-ÿ]{3,}", candidate):
                parsed["client_name"] = candidate[:200]
                break
    invoice = create_draft_invoice_from_parsed(company, parsed, source_name=filename)
    return invoice, parsed
