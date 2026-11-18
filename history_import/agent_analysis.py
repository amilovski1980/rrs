# Analyse par l'agent IA de document d'import (factures, releves, produits).
# Le fichier est ajoute a la fin (gagne sur tout). Exige text_provider configure.
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from django.utils import timezone

KIND_ALIASES = {
    "facture de vente": "sale_invoice",
    "facture_vente": "sale_invoice",
    "vente": "sale_invoice",
    "facture fournisseur": "purchase_invoice",
    "facture_fournisseur": "purchase_invoice",
    "achat": "purchase_invoice",
    "avoir": "credit_note",
    "ticket": "ticket",
    "justificatif": "ticket",
    "catalogue": "catalogue",
    "produits": "catalogue",
    "produit": "catalogue",
    "sumup": "sumup_transactions",
    "encaissements": "sumup_transactions",
    "ventes par produit": "product_sales",
    "ventes_produits": "product_sales",
    "releve bancaire": "bank_statement",
    "releve_bancaire": "bank_statement",
    "releve": "bank_statement",
    "banque": "bank_statement",
    "autre": "other",
    "inconnu": "unknown",
}


def _agent_chat(prompt: str, *, temperature: float = 0.1, max_tokens: int = 900,
                timeout: float = 55.0) -> str:
    """Appel chat/completions sur le fournisseur texte configure (qwen/xai/ollama)."""
    import httpx

    from ai.providers import text_provider

    provider = text_provider()
    if not provider.get("configured"):
        raise RuntimeError(
            "Aucun modéle IA texte configuré — réglez-le dans Configuration (IA)."
        )
    response = httpx.post(
        provider["base"].rstrip("/") + "/chat/completions",
        headers={"Authorization": "Bearer " + provider["key"]} if provider.get("key") else {},
        json={
            "model": provider["model"],
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    choice = (payload.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    return (message.get("content") or "").strip()


def _parse_agent_json(text: str) -> dict:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t).strip()
    match = re.search(r"\{.*\}", t, re.S)
    if match:
        t = match.group(0)
    data = json.loads(t)
    if not isinstance(data, dict):
        raise ValueError("La réponse de l'agent n'est pas un objet JSON.")
    return data


def _agent_content(document, limit: int = 6000) -> str:
    """Contenu lisible pour l'agent : texte connu, sinon decodage / OCR."""
    if (document.raw_text or "").strip():
        return document.raw_text.strip()[:limit]
    data = bytes(document.file_data) if document.file_data else b""
    if not data and document.file:
        try:
            data = document.file.read()
            document.file.seek(0)
        except Exception:
            data = b""
    if not data:
        return ""
    name = (document.original_name or "").lower()
    ctype = (document.content_type or "").lower()
    if "pdf" in ctype or name.endswith(".pdf"):
        try:
            from documents.receipt_ocr import extract_pdf_text_or_ocr

            return extract_pdf_text_or_ocr(data)[:limit]
        except Exception:
            pass
    if "image/" in ctype or name.endswith((".jpg", ".jpeg", ".png", ".webp")):
        try:
            from documents.receipt_ocr import transcribe_with_agent

            return transcribe_with_agent(data, filename=document.original_name or "")[:limit]
        except Exception:
            pass
    return data.decode("utf-8", errors="replace")[:limit]


def agent_analyze_document(document, user=None) -> dict:
    """L'agent IA lit le document : type, client, fournisseur, montage des
    montants. Non destructif : ne remplit que les champs vides."""
    from .services import audit

    content = _agent_content(document)
    if not content.strip():
        raise RuntimeError("Document illisible pour l'agent (aucun contenu).")

    prompt = (
        "Tu es l'assistant comptable Aminia. Analyse le document ci-dessous.\n"
        "Réponds UNIQUEMENT avec un JSON valide, sans texte autour:\n"
        '  {"kind": "facture_vente|facture_fournisseur|avoir|ticket|catalogue|'
        'sumup|ventes_produits|releve_bancaire|autre|inconnu",\n'
        '   "client": "", "fournisseur": "", "numero": "", "date": "YYYY-MM-DD",\n'
        '   "montant_ht": "0.00", "montant_tva": "0.00", "montant_ttc": "0.00",\n'
        '   "lignes": 0, "explication": "une phrase en français"}\n'
        "Si un champ est absent, laisse-le vide.\n\n"
        "Fichier: " + (document.original_name or "") + "\n"
        "Contenu:\n" + content
    )
    answer = _agent_chat(prompt)
    data = _parse_agent_json(answer)
    if isinstance(data.get("lignes"), int) is False and data.get("lignes"):
        data["lignes"] = int(re.sub(r"[^\d]", "", str(data["lignes"])) or 0)

    document.agent_json = data
    document.agent_text = answer

    kind_raw = str(data.get("kind") or "").strip().lower()
    mapped = KIND_ALIASES.get(kind_raw, "")
    if mapped and document.kind in ("", "unknown", "other"):
        document.kind = mapped

    _fill(document, "customer_name", data.get("client"))
    _fill(document, "seller_name", data.get("fournisseur"))
    _fill(document, "invoice_number", data.get("numero"))
    _fill_date(document, "invoice_date", data.get("date"))
    _fill_amount(document, "amount_ht", data.get("montant_ht"))
    _fill_amount(document, "amount_vat", data.get("montant_tva"))
    _fill_amount(document, "amount_ttc", data.get("montant_ttc"))

    if document.status in ("queued", "error"):
        document.status = "review"
    document.save()
    audit(document.company, "agent_analysis",
          document=document, user=user,
          detail=(data.get("explication") or "")[:180])
    return data


def _attr_set(document, field):
    current = getattr(document, field, None)
    if isinstance(current, str) and current.strip() == "":
        return True
    return current in (None, "")


def _fill(document, field, value):
    value = (str(value) or "").strip() if value is not None else ""
    if value and _attr_set(document, field):
        setattr(document, field, value)


def _fill_date(document, field, value):
    value = (str(value) or "").strip() if value is not None else ""
    if not value:
        return
    match = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", value)
    if not match:
        return
    try:
        parsed = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return
    if _attr_set(document, field):
        setattr(document, field, parsed)


def _fill_amount(document, field, value):
    value = (str(value) or "").strip() if value is not None else ""
    if not value:
        return
    value = value.replace(" ", "").replace("€", "")
    try:
        parsed = Decimal(value.replace(",", "."))
    except (InvalidOperation, ValueError):
        return
    if getattr(document, field) in (None, ""):
        setattr(document, field, parsed)


def agent_analyze_batch(batch, user=None, limit: int = 4) -> dict:
    """Fait lire l'agent sur les documents non résolus d'un lot."""
    from .models import ImportDocument

    done, errors = 0, 0
    details = []
    targets = list(
        batch.documents.exclude(
            status__in=("duplicate", "imported", "rejected")
        ).order_by("-created_at")[:limit]
    )
    for document in targets:
        try:
            agent_analyze_document(document, user=user)
            done += 1
        except Exception as exc:
            errors += 1
            details.append(document.original_name[:40] + ": " + str(exc)[:110])
    _try_refresh_status(batch)
    return {"done": done, "errors": errors, "details": details}


def _try_refresh_status(batch):
    from .services import _refresh_batch_status

    try:
        _refresh_batch_status(batch)
    except Exception:
        pass
