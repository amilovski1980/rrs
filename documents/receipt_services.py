"""Brouillons comptables liés aux tickets de caisse (validation humaine)."""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from accounting.models import EntryLine, JournalEntry

from .models import TicketDeCaisse

# Comptes disponibles dans generate_portal
CATEGORY_ACCOUNT = {
    "carburant": "625",
    "restauration": "625",
    "fournitures": "626",
    "transport": "625",
    "deplacement": "625",
    "autre": "626",
}


def _payment_credit_account(ticket: TicketDeCaisse) -> str:
    raw = (ticket.moyen_paiement or "").lower()
    if any(k in raw for k in ("espèce", "espece", "liquide", "cash")):
        return "530"
    if any(
        k in raw
        for k in (
            "cb",
            "carte",
            "visa",
            "master",
            "sans contact",
            "apple",
            "google",
            "virement",
        )
    ):
        return "512"
    return "401"


def propose_ticket_entry(ticket: TicketDeCaisse) -> JournalEntry:
    """Crée une écriture ACH brouillon équilibrée liée au ticket. Ne valide pas."""
    company = ticket.company
    if ticket.journal_entry_id and ticket.journal_entry and not ticket.journal_entry.validated:
        return ticket.journal_entry

    journal = company.journals.filter(code="ACH").first()
    if journal is None:
        raise ValueError("Journal ACH introuvable pour cette société.")

    expense_code = CATEGORY_ACCOUNT.get(ticket.categorie, "626")
    expense = company.accounts.filter(code=expense_code).first()
    if expense is None:
        expense = company.accounts.filter(code="626").first()
    credit_code = _payment_credit_account(ticket)
    credit_acc = company.accounts.filter(code=credit_code).first()
    if credit_acc is None:
        credit_acc = company.accounts.filter(code="401").first()
    if expense is None or credit_acc is None:
        raise ValueError("Plan comptable incomplet (625/626 ou 401/512/530).")

    ttc = ticket.montant_ttc.quantize(Decimal("0.01"))
    tva = (ticket.montant_tva or Decimal("0.00")).quantize(Decimal("0.01"))
    if tva < 0:
        tva = Decimal("0.00")
    if tva > ttc:
        tva = ttc
    ht = (ttc - tva).quantize(Decimal("0.01"))

    vat_acc = None
    if tva > 0:
        vat_acc = company.accounts.filter(code="44566").first()
        if vat_acc is None:
            # Pas de TVA déductible : tout en charge TTC
            ht = ttc
            tva = Decimal("0.00")

    label = f"Ticket {ticket.magasin or 'caisse'}".strip()[:200]
    with transaction.atomic():
        entry = JournalEntry.objects.create(
            company=company,
            journal=journal,
            date=ticket.date,
            label=label,
            reference=f"TK-{str(ticket.id)[:8]}",
            drafted_by_ai=True,
            validated=False,
        )
        EntryLine.objects.create(entry=entry, account=expense, debit=ht, credit=Decimal("0.00"))
        if vat_acc is not None and tva > 0:
            EntryLine.objects.create(
                entry=entry, account=vat_acc, debit=tva, credit=Decimal("0.00")
            )
        EntryLine.objects.create(
            entry=entry, account=credit_acc, debit=Decimal("0.00"), credit=ttc
        )
        ticket.journal_entry = entry
        ticket.save(update_fields=["journal_entry", "updated_at"])
    return entry


def validate_ticket(ticket: TicketDeCaisse) -> JournalEntry:
    """Passe le ticket en validé et s'assure qu'une écriture brouillon existe.

    L'écriture reste non validée au grand livre jusqu'à confirmation comptable
    séparée (même principe que pdf_import / propose_entry).
    """
    entry = propose_ticket_entry(ticket)
    if ticket.statut != "valide":
        ticket.statut = "valide"
        ticket.save(update_fields=["statut", "updated_at"])
    return entry
