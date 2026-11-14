"""Orchestration du connecteur e-mail comptable.

Deux responsabilités, testables séparément :

1. ``sync_mailbox``  : boîte e-mail → ``ProcessedEmail`` (anti-doublon) →
   ``SupplierInvoiceDraft`` (brouillon, aucun impact comptable).
2. ``validate_draft`` : brouillon validé par un humain → ``JournalEntry``
   équilibrée dans le journal d'achats + justificatif archivé.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from accounting.models import ChartAccount, EntryLine, Journal, JournalEntry

from .matching import create_supplier, find_matching_supplier
from .models import MailboxConfig, ProcessedEmail, SupplierInvoiceDraft
from .parsers import parse_attachment
from .providers import ProviderAuthError, ProviderError
from .tokens import build_adapter

logger = logging.getLogger(__name__)

MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024
SUPPORTED_EXTENSIONS = (".pdf", ".xml")
SYNC_LOOKBACK = timedelta(days=90)
STEP = Decimal("0.01")


class DraftValidationError(Exception):
    """Le brouillon ne peut pas être transformé en écriture en l'état."""


@dataclass
class SyncResult:
    company: str = ""
    scanned: int = 0
    imported: int = 0
    skipped: int = 0
    errors: int = 0
    detail: str = ""

    def summary(self) -> str:
        parts = [
            f"{self.scanned} message(s) examiné(s)",
            f"{self.imported} brouillon(s) créé(s)",
        ]
        if self.skipped:
            parts.append(f"{self.skipped} ignoré(s)")
        if self.errors:
            parts.append(f"{self.errors} erreur(s)")
        return " · ".join(parts)


# ---------------------------------------------------------------------------
# Planification
# ---------------------------------------------------------------------------
def is_due(config, now=None) -> bool:
    """La société doit-elle être interrogée maintenant ?"""
    if not config.is_active:
        return False
    now = now or timezone.now()
    if config.last_sync_at is None:
        return True
    return config.last_sync_at + timedelta(minutes=config.frequency_minutes) <= now


def claim_for_sync(config, *, force: bool = False) -> bool:
    """Réserve la société de façon atomique avant un run.

    Évite que deux crons qui se chevauchent interrogent la même boîte. Le
    ``UPDATE ... WHERE last_sync_at <= cutoff`` est atomique en base, sans
    verrou long tenu pendant les appels réseau.
    """
    now = timezone.now()
    queryset = MailboxConfig.objects.filter(pk=config.pk, is_active=True)
    if not force:
        cutoff = now - timedelta(minutes=config.frequency_minutes)
        queryset = queryset.filter(
            Q(last_sync_at__isnull=True) | Q(last_sync_at__lte=cutoff)
        )
    return queryset.update(last_sync_at=now) == 1


# ---------------------------------------------------------------------------
# Synchronisation
# ---------------------------------------------------------------------------
def sync_mailbox(config, *, adapter=None) -> SyncResult:
    """Interroge une boîte et transforme les factures en brouillons.

    ``adapter`` est injectable pour les tests (fake provider). Toute erreur
    d'un message est isolée : une pièce jointe cassée ne bloque jamais la
    boîte entière.
    """
    result = SyncResult(company=config.company.denomination)
    if not config.is_active:
        result.detail = "Boîte inactive."
        return result

    try:
        if adapter is None:
            adapter = build_adapter(config)
        account_email, account_id = adapter.fetch_account()
        if account_email:
            config.email_address = account_email
        if account_id:
            config.provider_account_id = account_id
        since = config.last_sync_at or (timezone.now() - SYNC_LOOKBACK)
        messages = adapter.list_messages(folder=config.folder_label or "", since=since)
    except ProviderAuthError as exc:
        _mark_error(config, str(exc))
        result.errors += 1
        result.detail = str(exc)
        return result
    except ProviderError as exc:
        _mark_error(config, str(exc))
        result.errors += 1
        result.detail = str(exc)
        return result

    result.scanned = len(messages)
    for message in messages:
        processed, created = ProcessedEmail.objects.get_or_create(
            config=config,
            message_id=message.message_id,
            defaults={
                "subject": message.subject[:255],
                "from_email": (message.from_email or "")[:254],
                "received_at": message.received_at,
                "status": "skipped",
                "detail": "Traitement en cours",
            },
        )
        if not created:
            # Anti-doublon strict : message déjà vu lors d'un run précédent.
            result.skipped += 1
            continue
        try:
            draft = _import_message(config, message, processed, adapter)
        except Exception as exc:  # une pièce cassée ne bloque pas la boîte
            logger.exception("Échec d'import du message %s", message.message_id)
            processed.status = "error"
            processed.detail = str(exc)[:255]
            processed.save(update_fields=["status", "detail"])
            result.errors += 1
            continue
        if draft is None:
            result.skipped += 1
        else:
            result.imported += 1

    config.last_sync_at = timezone.now()
    config.status = "connected"
    config.last_error = ""
    config.save(
        update_fields=[
            "email_address",
            "provider_account_id",
            "last_sync_at",
            "status",
            "last_error",
            "updated_at",
        ]
    )
    return result


def _mark_error(config, message: str) -> None:
    config.status = "error"
    config.last_error = (message or "")[:500]
    config.save(update_fields=["status", "last_error", "updated_at"])


def _import_message(config, message, processed, adapter):
    """Tente chaque pièce jointe jusqu'à en tirer une facture exploitable."""
    candidates = [
        attachment
        for attachment in message.attachments
        if attachment.filename.lower().endswith(SUPPORTED_EXTENSIONS)
        and (attachment.size <= 0 or attachment.size <= MAX_ATTACHMENT_BYTES)
    ]
    if not candidates:
        processed.detail = "Aucune pièce jointe PDF/XML"
        processed.save(update_fields=["detail"])
        return None

    extracted = None
    chosen = None
    payload = b""
    last_error = ""
    for attachment in candidates:
        try:
            payload = adapter.open_attachment(message, attachment)
        except ProviderError as exc:
            last_error = str(exc)
            continue
        if not payload:
            continue
        parsed = parse_attachment(attachment.filename, payload)
        if parsed is not None:
            extracted, chosen = parsed, attachment
            break

    if extracted is None:
        processed.detail = (last_error or "Pièce jointe non exploitable")[:255]
        processed.save(update_fields=["detail"])
        return None

    supplier = find_matching_supplier(
        config.company,
        name=extracted.supplier_name,
        siret=extracted.supplier_siret,
        vat=extracted.supplier_vat,
        email=message.from_email,
    )
    journal = config.journal or Journal.objects.filter(
        company=config.company, code="ACH"
    ).first()
    proposed_name = (
        supplier.name
        if supplier
        else (extracted.supplier_name or message.from_name or message.from_email)
    )

    draft = SupplierInvoiceDraft(
        company=config.company,
        config=config,
        journal=journal,
        supplier=supplier,
        proposed_supplier_name=(proposed_name or "Fournisseur")[:200],
        supplier_siret=(extracted.supplier_siret or "")[:20],
        supplier_vat=(extracted.supplier_vat or "")[:20],
        supplier_email=(message.from_email or "")[:254],
        invoice_number=(extracted.invoice_number or "")[:50],
        invoice_date=extracted.invoice_date,
        amount_ht=extracted.amount_ht,
        amount_vat=extracted.amount_vat,
        amount_ttc=extracted.amount_ttc,
        vat_rate=extracted.vat_rate,
        charge_account_code=(
            supplier.default_charge_code
            if supplier is not None and supplier.default_charge_code
            else config.charge_account_code
        ),
        vat_account_code=config.vat_account_code,
        supplier_account_root=config.supplier_account_root,
        source=extracted.source,
        raw_text=(extracted.raw_text or "")[:20000],
        attachment_name=(chosen.filename or "")[:255],
        status="pending",
    )

    safe_name = _safe_filename(chosen.filename)
    draft.attachment.save(safe_name, ContentFile(payload), save=False)

    with transaction.atomic():
        draft.save()
        processed.status = "imported"
        processed.detail = f"{chosen.filename} importé"[:255]
        processed.draft = draft
        processed.save(update_fields=["status", "detail", "draft"])
    return draft


def _safe_filename(name: str) -> str:
    base, _, extension = (name or "facture.pdf").rpartition(".")
    if not base:
        base, extension = "facture", "pdf"
    extension = (extension or "pdf").lower()[:8]
    return f"{slugify(base)[:80] or 'facture'}.{extension}"


# ---------------------------------------------------------------------------
# Validation humaine
# ---------------------------------------------------------------------------
def resolve_account(company, code: str, *, label: str = "", roots: tuple = ()):
    """Trouve un compte du plan, par code exact puis par racine, sinon le crée.

    Exemple : ``445660`` demandé mais plan existant en ``44566`` → le compte
    existant est utilisé plutôt que d'en créer un doublon.
    """
    code = (code or "").strip().upper()
    if not code:
        return None
    account = ChartAccount.objects.filter(company=company, code=code).first()
    if account:
        return account
    for root in roots:
        account = (
            ChartAccount.objects.filter(company=company, code__startswith=root)
            .order_by("code")
            .first()
        )
        if account:
            return account
    return ChartAccount.objects.create(
        company=company, code=code, label=(label or code)[:100]
    )


@transaction.atomic
def validate_draft(
    draft, *, supplier_name: str = "", journal: Journal | None = None
) -> JournalEntry:
    """Transforme un brouillon en écriture d'achat équilibrée et validée."""
    locked = SupplierInvoiceDraft.objects.select_for_update().get(pk=draft.pk)
    if locked.status != "pending":
        raise DraftValidationError("Ce brouillon a déjà été traité.")

    company = locked.company
    journal = (
        journal
        or locked.journal
        or Journal.objects.filter(company=company, code="ACH").first()
    )
    if journal is None:
        raise DraftValidationError(
            "Aucun journal d'achats (ACH) pour cette société. Générez d'abord le "
            "portail comptable."
        )

    supplier = locked.supplier
    if supplier is None:
        name = (
            supplier_name
            or locked.proposed_supplier_name
            or locked.supplier_email
            or "Fournisseur"
        ).strip()
        supplier = find_matching_supplier(
            company,
            name=name,
            siret=locked.supplier_siret,
            vat=locked.supplier_vat,
            email=locked.supplier_email,
        )
        if supplier is None:
            supplier = create_supplier(
                company,
                name=name,
                siret=locked.supplier_siret,
                vat=locked.supplier_vat,
                email=locked.supplier_email,
                charge_code=locked.charge_account_code,
            )

    # Anti-doublon métier : une même facture fournisseur ne doit pas être
    # enregistrée deux fois, même si elle arrive dans deux e-mails distincts.
    if locked.invoice_number:
        from purchases.models import PurchaseInvoice

        duplicate = (
            PurchaseInvoice.objects.filter(
                company=company,
                supplier=supplier,
                number=locked.invoice_number,
            )
            .exclude(mailsync_draft=locked)
            .exists()
        )
        if duplicate:
            raise DraftValidationError(
                f"La facture {locked.invoice_number} est déjà enregistrée dans les achats."
            )

    charge_account = resolve_account(
        company, locked.charge_account_code, label="Achats", roots=("606", "60")
    )
    if charge_account is None:
        raise DraftValidationError("Compte de charge manquant sur le brouillon.")
    supplier_account = resolve_account(
        company, locked.supplier_account_root, label="Fournisseurs", roots=("401",)
    )

    # Franchise en base : la TVA n'est pas déductible, la charge porte le TTC.
    if company.tva == "reel":
        amount_vat = locked.amount_vat
        amount_ht = locked.amount_ht
        amount_ttc = locked.amount_ttc
        if amount_ht <= 0 and amount_ttc > 0:
            amount_ht = (amount_ttc - amount_vat).quantize(STEP)
        if amount_ttc <= 0:
            amount_ttc = (amount_ht + amount_vat).quantize(STEP)
        if amount_ht <= 0 or amount_ttc <= 0:
            raise DraftValidationError("Montants incomplets : vérifiez HT et TTC.")
        if abs((amount_ht + amount_vat) - amount_ttc) > Decimal("0.02"):
            raise DraftValidationError(
                "HT + TVA n'est pas égal au TTC. Corrigez les montants."
            )
        # Rééquilibrage au centime près (arrondis de TVA).
        amount_ttc = (amount_ht + amount_vat).quantize(STEP)
    else:
        amount_vat = Decimal("0.00")
        amount_ttc = locked.amount_ttc or (locked.amount_ht + locked.amount_vat)
        amount_ttc = amount_ttc.quantize(STEP)
        amount_ht = amount_ttc
        if amount_ttc <= 0:
            raise DraftValidationError("Renseignez le montant TTC de la facture.")

    if amount_vat > 0:
        vat_account = resolve_account(
            company, locked.vat_account_code, label="TVA déductible", roots=("44566", "4456")
        )
        if vat_account is None:
            raise DraftValidationError("Compte de TVA déductible manquant.")
    else:
        vat_account = None

    if (amount_ht + amount_vat) != amount_ttc:
        raise DraftValidationError("Écriture non équilibrée : HT + TVA ≠ TTC.")

    label_parts = [supplier.name, locked.invoice_number or "facture"]
    label = " — ".join(part for part in label_parts if part)[:200]

    entry = JournalEntry.objects.create(
        company=company,
        journal=journal,
        date=locked.invoice_date or timezone.localdate(),
        label=label,
        reference=(locked.invoice_number or "")[:50],
        validated=True,
    )
    EntryLine.objects.create(
        entry=entry, account=charge_account, debit=amount_ht, credit=Decimal("0.00")
    )
    if vat_account is not None and amount_vat > 0:
        EntryLine.objects.create(
            entry=entry, account=vat_account, debit=amount_vat, credit=Decimal("0.00")
        )
    EntryLine.objects.create(
        entry=entry,
        account=supplier_account,
        debit=Decimal("0.00"),
        credit=amount_ttc,
    )

    locked.supplier = supplier
    locked.journal = journal
    locked.entry = entry
    locked.status = "validated"
    locked.validated_at = timezone.now()
    locked.save(
        update_fields=[
            "supplier",
            "journal",
            "entry",
            "status",
            "validated_at",
        ]
    )
    # Le registre achats reprend la facture validée (une seule écriture).
    from purchases.services import record_mailsync_purchase

    record_mailsync_purchase(locked, entry, supplier)
    return entry


def ignore_draft(draft) -> SupplierInvoiceDraft:
    """Marque un brouillon comme ignoré (le message reste anti-doublonné)."""
    if draft.status == "pending":
        draft.status = "ignored"
        draft.save(update_fields=["status"])
    return draft
