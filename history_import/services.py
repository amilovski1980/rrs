"""Analyse, classification et import des documents historiques.

Réutilise les parseurs Factur-X/UBL/PDF et l'OCR tickets existants. Aucune
écriture comptable n'est créée : les factures importées sont archivées.
"""

from __future__ import annotations

import hashlib
import io
import logging
import mimetypes
import re
import zipfile
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import PurePosixPath

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.utils import timezone
from django.utils.text import get_valid_filename

from documents.models import Client, Invoice
from documents.receipt_ocr import ReceiptOcrError, extract_receipt_text
from mailsync.matching import create_supplier, find_matching_supplier
from mailsync.parsers import parse_attachment
from mailsync.parsers.pdf_invoice import parse_text
from mailsync.parsers.schema import ExtractedInvoice
from purchases.models import PurchaseInvoice

from .models import ImportAuditEvent, ImportBatch, ImportDocument

logger = logging.getLogger(__name__)

MAX_FILES = int(getattr(settings, "HISTORY_IMPORT_MAX_FILES", 200))
MAX_FILE_BYTES = int(getattr(settings, "HISTORY_IMPORT_MAX_FILE_MB", 15)) * 1024 * 1024
MAX_BATCH_BYTES = int(getattr(settings, "HISTORY_IMPORT_MAX_BATCH_MB", 150)) * 1024 * 1024
MAX_ZIP_FILES = int(getattr(settings, "HISTORY_IMPORT_MAX_ZIP_FILES", 100))
MAX_ZIP_BYTES = int(getattr(settings, "HISTORY_IMPORT_MAX_ZIP_MB", 150)) * 1024 * 1024

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".xml",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".heic",
    ".heif",
}
ZIP_EXTENSIONS = {".zip"}

STEP = Decimal("0.01")
ZERO = Decimal("0.00")


class HistoricalImportError(Exception):
    """Erreur métier avec un message utilisateur en français."""


# ---------------------------------------------------------------------------
# Upload & validation
# ---------------------------------------------------------------------------
def _extension(name: str) -> str:
    lowered = (name or "").lower()
    return f".{lowered.rsplit('.', 1)[-1]}" if "." in lowered else ""


def _mime(name: str, provided: str = "") -> str:
    ctype = (provided or "").split(";")[0].strip().lower()
    if ctype and ctype != "application/octet-stream":
        return ctype
    return mimetypes.guess_type(name or "")[0] or "application/octet-stream"


def validate_file(name: str, data: bytes, content_type: str = "") -> None:
    extension = _extension(name)
    if extension not in ALLOWED_EXTENSIONS:
        raise HistoricalImportError(
            f"Type de fichier non autorisé : {extension or 'inconnu'}. "
            "Formats acceptés : PDF, XML, JPG, PNG, WEBP, HEIC."
        )
    if not data:
        raise HistoricalImportError(f"Le fichier {name} est vide.")
    if len(data) > MAX_FILE_BYTES:
        raise HistoricalImportError(
            f"Le fichier {name} dépasse {MAX_FILE_BYTES // (1024 * 1024)} Mo."
        )
    mimetype = _mime(name, content_type)
    if mimetype in {"application/x-dosexec", "application/x-msdownload"}:
        raise HistoricalImportError(f"Fichier exécutable refusé : {name}.")
    try:
        import magic

        detected = (magic.from_buffer(data[:4096], mime=True) or "").lower()
    except Exception:
        detected = ""
    if detected in {"application/x-dosexec", "application/x-msdownload"}:
        raise HistoricalImportError(f"Fichier exécutable refusé : {name}.")
    if extension == ".pdf" and detected and detected not in (
        "application/pdf",
        "application/octet-stream",
    ):
        raise HistoricalImportError(f"Le fichier {name} n'est pas un PDF valide.")
    if extension == ".pdf" and mimetype not in ("application/pdf", "application/octet-stream"):
        raise HistoricalImportError(f"Le fichier {name} n'est pas un PDF valide.")


def safe_extract_zip(data: bytes) -> list[tuple[str, bytes, str]]:
    """Extrait une archive en mémoire, sans écrire sur le disque."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise HistoricalImportError("Archive ZIP illisible ou corrompue.") from exc
    entries: list[tuple[str, bytes, str]] = []
    total = 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        if info.flag_bits & 0x1:
            raise HistoricalImportError("Les archives ZIP protégées par mot de passe sont refusées.")
        if len(archive.infolist()) > MAX_ZIP_FILES * 4:
            raise HistoricalImportError("Archive ZIP : trop de fichiers internes.")
        name = info.filename.replace("\\", "/")
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            raise HistoricalImportError("Archive ZIP non sécurisée : chemin interdit.")
        if _extension(name) not in ALLOWED_EXTENSIONS:
            continue
        if info.file_size > MAX_FILE_BYTES:
            raise HistoricalImportError(f"Le fichier {name} dépasse la taille autorisée.")
        total += info.file_size
        if total > MAX_ZIP_BYTES:
            raise HistoricalImportError("Archive ZIP trop volumineuse après décompression.")
        if len(entries) >= MAX_ZIP_FILES:
            raise HistoricalImportError(
                f"Archive ZIP : maximum {MAX_ZIP_FILES} documents par archive."
            )
        try:
            payload = archive.read(info)
        except (RuntimeError, zipfile.BadZipFile) as exc:
            raise HistoricalImportError(f"Impossible de lire {name} dans l'archive.") from exc
        validate_file(name, payload, _mime(name))
        entries.append((name, payload, _mime(name)))
    archive.close()
    if not entries:
        raise HistoricalImportError("Aucun document PDF/image/XML dans l'archive ZIP.")
    return entries


def audit(company, action: str, *, batch=None, document=None, user=None, detail=""):
    ImportAuditEvent.objects.create(
        company=company,
        batch=batch,
        document=document,
        user=user,
        action=action,
        detail=(detail or "")[:2000],
    )


def create_batch(company, user, *, label="", kind_hint=""):
    batch = ImportBatch.objects.create(
        company=company,
        created_by=user,
        label=(label or "").strip()[:120],
        kind_hint=kind_hint if kind_hint in ("sale_invoice", "purchase_invoice") else "",
    )
    audit(company, "batch_created", batch=batch, user=user)
    return batch


def _create_document(batch, company, name, data, content_type, user=None):
    if batch.documents.count() >= MAX_FILES:
        raise HistoricalImportError(
            f"Ce lot contient déjà {MAX_FILES} documents : créez un nouveau lot."
        )
    current_size = sum(batch.documents.values_list("size", flat=True))
    if current_size + len(data) > MAX_BATCH_BYTES:
        raise HistoricalImportError(
            f"Ce lot dépasse {MAX_BATCH_BYTES // (1024 * 1024)} Mo : créez un nouveau lot."
        )
    checksum = hashlib.sha256(data).hexdigest()
    previous = (
        ImportDocument.objects.filter(company=company, checksum=checksum)
        .order_by("created_at")
        .first()
    )
    duplicate = previous is not None
    document = ImportDocument(
        batch=batch,
        company=company,
        original_name=(name or "document")[:255],
        content_type=content_type[:120],
        size=len(data),
        checksum=checksum,
        status="duplicate" if duplicate else "queued",
        duplicate_of=previous,
        duplicate_reason="Fichier identique déjà importé." if duplicate else "",
        file_data=data,
    )
    filename = get_valid_filename(name or "document")
    try:
        document.file.save(filename, ContentFile(data), save=False)
    except OSError:
        # Le système de fichiers serverless est en lecture seule.
        document.file = None
    document.save()
    audit(
        company,
        "document_uploaded",
        batch=batch,
        document=document,
        user=user,
        detail=name,
    )
    return document


def add_upload(batch, upload, user=None):
    """Ajoute un fichier (ou une archive ZIP) au lot."""
    name = upload.name or "document"
    data = upload.read()
    content_type = _mime(name, getattr(upload, "content_type", ""))
    if _extension(name) in ZIP_EXTENSIONS:
        entries = safe_extract_zip(data)
        documents = [
            _create_document(batch, batch.company, entry_name, payload, entry_mime, user)
            for entry_name, payload, entry_mime in entries
        ]
        audit(
            batch.company,
            "zip_extracted",
            batch=batch,
            user=user,
            detail=f"{len(documents)} document(s) extrait(s) de {name}",
        )
        return documents
    validate_file(name, data, content_type)
    return [_create_document(batch, batch.company, name, data, content_type, user)]


# ---------------------------------------------------------------------------
# Extraction & classification
# ---------------------------------------------------------------------------
def _serializable(invoice: ExtractedInvoice) -> dict:
    return {
        "supplier_name": invoice.supplier_name,
        "supplier_siret": invoice.supplier_siret,
        "supplier_vat": invoice.supplier_vat,
        "customer_name": invoice.customer_name,
        "customer_siret": invoice.customer_siret,
        "customer_vat": invoice.customer_vat,
        "invoice_number": invoice.invoice_number,
        "invoice_date": invoice.invoice_date.isoformat() if invoice.invoice_date else "",
        "amount_ht": str(invoice.amount_ht),
        "amount_vat": str(invoice.amount_vat),
        "amount_ttc": str(invoice.amount_ttc),
        "vat_rate": str(invoice.vat_rate),
        "currency": invoice.currency,
        "source": invoice.source,
    }


def _extract_document(document: ImportDocument) -> tuple[ExtractedInvoice | None, str, str]:
    if document.file_data:
        data = bytes(document.file_data)
    elif document.file:
        data = document.file.read()
    else:
        raise HistoricalImportError("Fichier original introuvable.")
    name = document.original_name.lower()
    content_type = document.content_type
    if name.endswith(".xml"):
        invoice = parse_attachment(document.original_name, data)
        return invoice, (invoice.raw_text if invoice else ""), "xml"
    if name.endswith(".pdf"):
        invoice = parse_attachment(document.original_name, data)
        if invoice is not None:
            return invoice, invoice.raw_text, "pdf"
        try:
            text = extract_receipt_text(data, document.original_name, content_type)
        except ReceiptOcrError as exc:
            return None, "", f"ocr_error:{exc}"
        return parse_text(text, source="ocr"), text, "ocr"
    try:
        text = extract_receipt_text(data, document.original_name, content_type)
    except ReceiptOcrError as exc:
        return None, "", f"ocr_error:{exc}"
    return parse_text(text, source="ocr"), text, "ocr"


def _normalize(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value or "").upper()


def _company_identity(company):
    data = company.source_data if isinstance(company.source_data, dict) else {}
    siret = re.sub(r"\D", "", str(data.get("siret") or ""))
    siren = re.sub(r"\D", "", company.siren or "")
    tva = _normalize(company.tva_intra_number)
    name = _normalize(company.denomination)
    return {"siret": siret, "siren": siren, "tva": tva, "name": name}


def _party_matches(siret: str, vat: str, name: str, company) -> bool:
    identity = _company_identity(company)
    digits = re.sub(r"\D", "", siret or "")
    vat_norm = _normalize(vat)
    name_norm = _normalize(name)
    if digits and (
        digits == identity["siret"]
        or digits == identity["siren"]
        or (identity["siret"] and digits in identity["siret"])
    ):
        return True
    if vat_norm and identity["tva"] and vat_norm == identity["tva"]:
        return True
    if name_norm and identity["name"] and (
        name_norm in identity["name"] or identity["name"] in name_norm
    ):
        return True
    return False


def _classify(invoice: ExtractedInvoice | None, raw_text: str, batch: ImportBatch):
    warnings: list[str] = []
    if invoice is None:
        return "unknown", warnings
    lowered = (raw_text or "").lower()
    if "avoir" in lowered or "credit note" in lowered or "gutschrift" in lowered:
        return "credit_note", warnings

    seller_match = _party_matches(
        invoice.supplier_siret, invoice.supplier_vat, invoice.supplier_name, batch.company
    )
    buyer_match = _party_matches(
        invoice.customer_siret, invoice.customer_vat, invoice.customer_name, batch.company
    )

    if seller_match and buyer_match:
        warnings.append("La société apparaît à la fois comme émetteur et destinataire.")
        return "unknown", warnings
    if seller_match:
        kind = "sale_invoice"
        if not invoice.customer_name:
            warnings.append("Client non identifié : à compléter.")
    elif buyer_match:
        kind = "purchase_invoice"
        if not invoice.supplier_name:
            warnings.append("Fournisseur non identifié : à compléter.")
    elif batch.kind_hint:
        kind = batch.kind_hint
        warnings.append("Identité de la société non confirmée : vérifiez la classification.")
    elif invoice.source == "ocr" and "ticket" in lowered and not invoice.invoice_number:
        kind = "ticket"
    elif invoice.supplier_name:
        kind = "purchase_invoice"
        warnings.append("Société non identifiée dans le document : vérifiez l'émetteur.")
    else:
        kind = "unknown"
        warnings.append("Document non reconnu : classez-le manuellement.")

    if kind in ("sale_invoice", "purchase_invoice"):
        if invoice.amount_ttc <= 0:
            warnings.append("Montant TTC manquant.")
        if invoice.amount_ht > 0 and invoice.amount_vat >= 0:
            if abs((invoice.amount_ht + invoice.amount_vat) - invoice.amount_ttc) > Decimal("0.02"):
                warnings.append("HT + TVA ne correspond pas au TTC.")
        if not invoice.invoice_number:
            warnings.append("Numéro de facture manquant.")
        if invoice.invoice_date is None:
            warnings.append("Date de facture manquante.")
    elif invoice.amount_ttc <= 0:
        warnings.append("Montant TTC manquant.")
    return kind, warnings


MAX_IMPORT_AMOUNT = Decimal("999999999999.99")  # précision 15/2 : 10^14


def _amounts_beyond_limit(invoice: ExtractedInvoice) -> list[str]:
    """Noms des montants qui dépassent la capacité du champ (10^14)."""
    beyond = []
    for label, value in (
        ("HT", invoice.amount_ht),
        ("TVA", invoice.amount_vat),
        ("TTC", invoice.amount_ttc),
    ):
        if abs(value or Decimal("0")) > MAX_IMPORT_AMOUNT:
            beyond.append(f"{label} {value}")
    return beyond


def _apply_extraction(document: ImportDocument, invoice: ExtractedInvoice | None):
    """Écrit les données extraites. Un montant hors échelle ne lève plus
    une erreur Postgres : le document passe en « error » avec un message
    lisible et des avertissements exploitables."""
    if invoice is None:
        return
    beyond = _amounts_beyond_limit(invoice)
    if beyond:
        document.warnings = list(document.warnings or []) + [
            f"Montant hors échelle ignoré : {', '.join(beyond)}"
        ]
        document.status = "error"
        document.error_message = (
            "Montant illisible : la fiche contient une valeur au-delà de "
            "999 999 999 999,99. Corrigez la lecture (montant, devise, "
            "concentration de chiffres) puis relancez l'analyse."
        )
        document.amount_ht = ZERO
        document.amount_vat = ZERO
        document.amount_ttc = ZERO
        document.vat_rate = invoice.vat_rate
        document.currency = invoice.currency or "EUR"
        document.extracted = {}
        return
    document.seller_name = invoice.supplier_name[:200]
    document.seller_siret = invoice.supplier_siret[:20]
    document.seller_vat = invoice.supplier_vat[:20]
    document.customer_name = invoice.customer_name[:200]
    document.customer_siret = invoice.customer_siret[:20]
    document.customer_vat = invoice.customer_vat[:20]
    document.invoice_number = invoice.invoice_number[:50]
    document.invoice_date = invoice.invoice_date
    document.amount_ht = invoice.amount_ht
    document.amount_vat = invoice.amount_vat
    document.amount_ttc = invoice.amount_ttc
    document.vat_rate = invoice.vat_rate
    document.currency = invoice.currency or "EUR"
    document.extracted = _serializable(invoice)


def _find_existing_invoice(document: ImportDocument):
    if document.invoice_number:
        same_batch = (
            ImportDocument.objects.filter(
                company=document.company,
                kind=document.kind,
                invoice_number=document.invoice_number,
                amount_ttc=document.amount_ttc,
            )
            .exclude(pk=document.pk)
            .exclude(status__in=["rejected", "error"])
            .first()
        )
        if same_batch is not None:
            return same_batch
    if document.kind == "sale_invoice" and document.invoice_number:
        return Invoice.objects.filter(
            company=document.company, number=document.invoice_number
        ).first()
    if document.kind == "purchase_invoice" and document.invoice_number:
        return PurchaseInvoice.objects.filter(
            company=document.company, number=document.invoice_number
        ).first()
    return None


def _mark_duplicate(document: ImportDocument, existing) -> bool:
    if existing is None:
        return False
    document.status = "duplicate"
    document.duplicate_reason = "Document déjà présent dans la société."
    if isinstance(existing, ImportDocument):
        document.duplicate_of = existing
    else:
        document.duplicate_reason = f"Déjà présent : {existing}"
    return True


def process_document(document: ImportDocument, user=None):
    """Analyse un document et le place en ready/review/duplicate/error."""
    if document.status == "imported":
        return document
    document.status = "processing"
    document.error_message = ""
    document.save(update_fields=["status", "error_message", "updated_at"])
    try:
        invoice, raw_text, source = _extract_document(document)
        document.raw_text = (raw_text or "")[:40000]
        kind, warnings = _classify(invoice, raw_text, document.batch)
        document.kind = kind
        document.warnings = warnings
        if invoice is not None:
            _apply_extraction(document, invoice)
        if source.startswith("ocr_error:"):
            document.error_message = source.split(":", 1)[1][:500]
            document.status = "review"
        elif invoice is None:
            document.status = "review"
            document.warnings = warnings + ["Aucune donnée exploitable : vérifiez le document."]
        else:
            existing = _find_existing_invoice(document)
            if _mark_duplicate(document, existing):
                pass
            else:
                blocking = any(
                    marker in warning
                    for warning in warnings
                    for marker in ("manquant", "non reconnu", "non identifié", "ne correspond", "non confirmée")
                )
                document.status = "review" if blocking else "ready"
        document.processed_at = timezone.now()
        document.save()
        audit(
            document.company,
            "document_processed",
            batch=document.batch,
            document=document,
            user=user,
            detail=f"{document.kind} / {document.status}",
        )
    except Exception as exc:  # un fichier cassé ne bloque pas le lot
        logger.exception("Analyse du document %s en échec", document.pk)
        document.status = "error"
        document.error_message = str(exc)[:500]
        document.save(update_fields=["status", "error_message", "updated_at"])
    return document


def process_batch(batch: ImportBatch, *, limit=None, user=None):
    pending = batch.documents.filter(status__in=["queued", "processing"])
    if limit:
        pending = pending[:limit]
    for document in list(pending):
        with transaction.atomic():
            process_document(document, user=user)
    _refresh_batch_status(batch)
    return batch_stats(batch)


def _refresh_batch_status(batch: ImportBatch):
    statuses = list(batch.documents.values_list("status", flat=True))
    if not statuses:
        batch.status = "queued"
    elif any(status in ("queued", "processing") for status in statuses):
        batch.status = "processing"
    elif all(status in ("imported", "duplicate", "rejected") for status in statuses):
        batch.status = "done"
    elif any(status == "ready" for status in statuses):
        batch.status = "ready"
    else:
        batch.status = "review"
    batch.save(update_fields=["status", "updated_at"])


def batch_stats(batch: ImportBatch) -> dict:
    counts = {key: 0 for key, _label in ImportDocument.STATUSES}
    for status, count in batch.documents.values_list("status").annotate(total=Count("id")):
        counts[status] = count
    total = sum(counts.values())
    return {
        "total": total,
        "pending": counts["queued"] + counts["processing"],
        "ready": counts["ready"],
        "review": counts["review"],
        "duplicates": counts["duplicate"],
        "imported": counts["imported"],
        "errors": counts["error"],
        "rejected": counts["rejected"],
        "counts": counts,
    }


# ---------------------------------------------------------------------------
# Correction & import
# ---------------------------------------------------------------------------
def refresh_document_status(document: ImportDocument):
    warnings: list[str] = []
    if document.kind in ("sale_invoice", "purchase_invoice"):
        if not document.invoice_number:
            warnings.append("Numéro de facture manquant.")
        if not document.invoice_date:
            warnings.append("Date de facture manquante.")
        if document.amount_ttc <= 0:
            warnings.append("Montant TTC manquant.")
        if document.kind == "sale_invoice" and not document.customer_name:
            warnings.append("Client non identifié.")
        if document.kind == "purchase_invoice" and not document.seller_name:
            warnings.append("Fournisseur non identifié.")
        if document.amount_ht > 0 and abs(
            (document.amount_ht + document.amount_vat) - document.amount_ttc
        ) > Decimal("0.02"):
            warnings.append("HT + TVA ne correspond pas au TTC.")
    elif document.amount_ttc <= 0:
        warnings.append("Montant TTC manquant.")
    document.warnings = list(dict.fromkeys(warnings))
    existing = _find_existing_invoice(document)
    if _mark_duplicate(document, existing):
        pass
    else:
        document.status = "review" if document.warnings else "ready"
    document.save()
    _refresh_batch_status(document.batch)
    return document


def _get_or_create_client(document: ImportDocument) -> Client:
    siren = re.sub(r"\D", "", document.customer_siret or "")[:9]
    name = (document.customer_name or "").strip()
    if not name:
        name = "Client historique (à compléter)"
    client = None
    if siren:
        client = Client.objects.filter(company=document.company, siren=siren).first()
    if client is None:
        client = Client.objects.filter(
            company=document.company, name__iexact=name
        ).first()
    if client is None:
        client = Client.objects.create(
            company=document.company,
            name=name[:200],
            siren=siren,
            tva_intra=document.customer_vat[:20],
        )
    return client


def _get_or_create_supplier(document: ImportDocument):
    supplier = find_matching_supplier(
        document.company,
        name=document.seller_name,
        siret=document.seller_siret,
        vat=document.seller_vat,
    )
    if supplier is None:
        supplier = create_supplier(
            document.company,
            name=document.seller_name or "Fournisseur historique",
            siret=document.seller_siret,
            vat=document.seller_vat,
            source="historical_import",
        )
    return supplier


def import_document(document: ImportDocument, user=None):
    """Importe un document prêt. Idempotent, sans écriture comptable."""
    if document.status == "imported":
        return document
    if document.status != "ready":
        raise HistoricalImportError("Ce document doit être vérifié avant import.")
    if document.kind not in (
        "sale_invoice",
        "purchase_invoice",
        "credit_note",
        "ticket",
        "other",
    ):
        raise HistoricalImportError("Ce type de document est archivé sans import métier.")

    existing = _find_existing_invoice(document)
    if existing is not None:
        _mark_duplicate(document, existing)
        document.save()
        return document

    if document.kind == "sale_invoice":
        if not document.invoice_number:
            raise HistoricalImportError("Le numéro de facture est obligatoire.")
        client = _get_or_create_client(document)
        try:
            invoice = Invoice.objects.create(
                company=document.company,
                number=document.invoice_number,
                client=client,
                client_name=document.customer_name or client.name,
                client_siren=re.sub(r"\D", "", document.customer_siret or "")[:9],
                client_tva_intra=document.customer_vat,
                amount_ht=document.amount_ht,
                vat_rate=document.vat_rate,
                due_date=document.due_date,
                status="archived",
                source="historical_import",
            )
        except IntegrityError:
            _mark_duplicate(document, Invoice.objects.filter(
                company=document.company, number=document.invoice_number
            ).first())
            document.save()
            return document
        if document.invoice_date:
            moment = timezone.make_aware(
                datetime.combine(document.invoice_date, time(12, 0))
            )
            Invoice.objects.filter(pk=invoice.pk).update(created_at=moment)
        document.imported_invoice = invoice
    elif document.kind == "purchase_invoice":
        if not document.invoice_number:
            raise HistoricalImportError("Le numéro de facture est obligatoire.")
        supplier = _get_or_create_supplier(document)
        try:
            purchase = PurchaseInvoice.objects.create(
                company=document.company,
                supplier=supplier,
                supplier_name=(document.seller_name or supplier.name)[:200],
                number=document.invoice_number,
                invoice_date=document.invoice_date,
                due_date=document.due_date,
                amount_ht=document.amount_ht,
                amount_vat=document.amount_vat,
                amount_ttc=document.amount_ttc,
                vat_rate=document.vat_rate,
                status="archived",
                source="historical_import",
                description=document.description,
                attachment_name=document.original_name[:255],
            )
        except IntegrityError:
            _mark_duplicate(document, PurchaseInvoice.objects.filter(
                company=document.company, number=document.invoice_number
            ).first())
            document.save()
            return document
        document.imported_purchase = purchase

    document.status = "imported"
    document.imported_at = timezone.now()
    document.save()
    audit(
        document.company,
        "document_imported",
        batch=document.batch,
        document=document,
        user=user,
        detail=f"{document.kind} {document.invoice_number}",
    )
    _refresh_batch_status(document.batch)
    return document


def import_ready_documents(batch: ImportBatch, document_ids=None, user=None):
    queryset = batch.documents.filter(status="ready")
    if document_ids:
        queryset = queryset.filter(pk__in=document_ids)
    imported = 0
    errors = 0
    for document in list(queryset):
        try:
            import_document(document, user=user)
            imported += 1
        except (HistoricalImportError, IntegrityError) as exc:
            errors += 1
            document.warnings = list(document.warnings or []) + [str(exc)]
            document.save(update_fields=["warnings"])
    _refresh_batch_status(batch)
    return {"imported": imported, "errors": errors}
