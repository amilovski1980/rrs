"""Assistant comptable vocal : lecture de la société et écritures brouillon.

Rien n'est passé au grand livre sans confirm_entry, appelé seulement après
un accord explicite de l'utilisateur.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q, Sum

from accounting.models import ChartAccount, Journal, JournalEntry, EntryLine
from companies.models import Company

JOURNALS = ("ACH", "VEN", "BQ", "CA", "OD")


def money(value):
    if value is None or value == "":
        return Decimal("0.00")
    try:
        amount = Decimal(str(value).replace(",", ".").replace(" ", "").replace("€", ""))
    except (InvalidOperation, ValueError):
        raise ValueError("montant illisible")
    return amount.quantize(Decimal("0.01"))


def owned_companies(user):
    return Company.objects.filter(owner=user).order_by("denomination")


def resolve_company(user, company_id=None):
    qs = owned_companies(user)
    if company_id:
        company = qs.filter(pk=company_id).first()
        if company is None:
            raise PermissionError("Cette société ne vous appartient pas.")
        return company
    return qs.first()


def company_card(company):
    return {
        "id": str(company.id),
        "denomination": company.denomination,
        "siren": company.siren,
        "forme": company.forme,
        "regime": company.get_regime_display(),
        "tva": company.get_tva_display(),
        "activites": company.activites or [],
        "exercice_debut": company.exercice_debut.isoformat() if company.exercice_debut else None,
    }


def balance_rows(company):
    validated = Q(entryline__entry__validated=True)
    per_account = ChartAccount.objects.filter(company=company).annotate(
        total_debit=Sum("entryline__debit", filter=validated),
        total_credit=Sum("entryline__credit", filter=validated),
    ).order_by("code")
    rows = []
    for account in per_account:
        debit = account.total_debit or Decimal("0")
        credit = account.total_credit or Decimal("0")
        if debit == 0 and credit == 0:
            continue
        rows.append({
            "code": account.code,
            "label": account.label,
            "debit": str(debit),
            "credit": str(credit),
            "solde": str(debit - credit),
        })
    return rows


def instructions_for(user, company):
    if company is None:
        return (
            "Tu es Aminia, assistante comptable vocale de Road Runner Solutions. "
            "Tu parles français, vouvoiement, phrases courtes. "
            "Cet utilisateur n'a pas encore de société. Dis-lui d'ajouter un SIREN "
            "depuis le cockpit. Ne invente aucun chiffre."
        )
    others = [
        f"{c.denomination} ({c.siren})"
        for c in owned_companies(user).exclude(pk=company.pk)[:5]
    ]
    extra = ""
    if others:
        extra = " Autres sociétés : " + ", ".join(others) + ". Utilise switch_company pour changer."
    return (
        "Tu es Aminia, assistante comptable vocale de Road Runner Solutions. "
        "Tu gères la comptabilité de la société "
        f"{company.denomination}, SIREN {company.siren}, "
        f"{company.get_forme_display() if hasattr(company, 'get_forme_display') else company.forme}, "
        f"régime {company.get_regime_display()}, TVA {company.get_tva_display()}. "
        "Tu parles français, vouvoiement, phrases très courtes, adaptées à la voix. "
        "Tu peux lire la société, la balance, le grand livre et les brouillons, "
        "proposer une écriture, rédiger une facture, et créer un brouillon de client. "
        "Pour une facture, appelle draft_invoice dès que tu as le client et le montant : "
        "l'écran affiche la saisie en direct, champ par champ. "
        "Dis les valeurs à voix haute pendant qu'elles s'écrivent. "
        "Une facture rédigée reste un brouillon : ne l'émets pas toi-même. "
        "Pour un nouveau client, appelle draft_client : cela crée seulement un brouillon "
        "à valider par un humain, jamais une fiche client définitive. "
        "Tu ne valides jamais une écriture ni un client sans un oui clair : "
        "d'abord propose_entry ou draft_client, tu relis, puis confirm_entry "
        "uniquement si l'utilisateur a dit oui pour une écriture. "
        "Les brouillons clients se valident dans l'écran Brouillons IA. "
        "N'invente aucun chiffre : appelle les outils. "
        "Montants en euros, au centime, débit égal au crédit."
        + extra
    )


TOOLS = [
    {
        "type": "function",
        "name": "get_company_overview",
        "description": "Fiche de la société en cours : identité, régime, TVA, activités.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "list_companies",
        "description": "Liste les sociétés de l'utilisateur.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "switch_company",
        "description": "Change la société gérée. À n'appeler que si l'utilisateur désigne une autre société.",
        "parameters": {
            "type": "object",
            "properties": {"company_id": {"type": "string", "description": "Identifiant UUID de la société"}},
            "required": ["company_id"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_balance",
        "description": "Balance des comptes validés de la société en cours.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "list_entries",
        "description": "Dernières écritures validées du grand livre.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Nombre de lignes, 1 à 15"},
                "query": {"type": "string", "description": "Filtre sur le libellé ou la référence"},
            },
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "list_drafts",
        "description": "Brouillons d'écritures proposés par l'assistant, pas encore validés.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "propose_entry",
        "description": (
            "Crée un brouillon d'écriture équilibrée. Ne la passe pas au grand livre. "
            "Relis ensuite les montants à voix haute et attends un oui."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "journal": {"type": "string", "enum": list(JOURNALS), "description": "ACH, VEN, BQ, CA ou OD"},
                "date": {"type": "string", "description": "Date ISO AAAA-MM-JJ"},
                "label": {"type": "string"},
                "reference": {"type": "string"},
                "lines": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "account_code": {"type": "string"},
                            "debit": {"type": "string"},
                            "credit": {"type": "string"},
                        },
                        "required": ["account_code"],
                    },
                },
            },
            "required": ["journal", "label", "lines"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "confirm_entry",
        "description": "Valide un brouillon déjà relu, seulement après un oui explicite de l'utilisateur.",
        "parameters": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string"},
                "confirmation": {"type": "string", "description": "Doit valoir exactement oui"},
            },
            "required": ["entry_id", "confirmation"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "draft_invoice",
        "description": (
            "Rédige un brouillon de facture. À appeler dès que le client et le montant HT "
            "sont connus. L'utilisateur voit les champs se remplir en direct. N'émet pas la facture."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "client_name": {"type": "string", "description": "Nom du client"},
                "client_siren": {"type": "string", "description": "SIREN à 9 chiffres, ou vide"},
                "amount_ht": {"type": "string", "description": "Montant hors taxe en euros"},
                "vat_rate": {"type": "string", "description": "Taux de TVA, par exemple 20 ou 0"},
                "designation": {"type": "string", "description": "Libellé de la prestation"},
            },
            "required": ["client_name", "amount_ht"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "draft_client",
        "description": (
            "Propose un brouillon de fiche client. Ne crée pas le client définitif : "
            "un humain doit valider le brouillon dans l'écran Brouillons IA."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Raison sociale ou nom du client"},
                "siren": {"type": "string", "description": "SIREN à 9 chiffres, ou vide"},
                "address": {"type": "string"},
                "email": {"type": "string"},
                "phone": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
]


def _entry_payload(entry):
    return {
        "id": str(entry.id),
        "date": entry.date.isoformat(),
        "journal": entry.journal.code,
        "label": entry.label,
        "reference": entry.reference,
        "validated": entry.validated,
        "lines": [
            {
                "account_code": line.account.code,
                "label": line.account.label,
                "debit": str(line.debit),
                "credit": str(line.credit),
            }
            for line in entry.lines.select_related("account")
        ],
    }


def execute_tool(user, company, name, args, session_company_setter=None):
    args = args or {}
    from admin_backoffice.agent_prompts import tool_allowed

    if not tool_allowed(user, name):
        return {"error": "Cette action n'est pas incluse dans votre forfait."}
    if name == "list_companies":
        return {"companies": [company_card(c) for c in owned_companies(user)]}

    if name == "switch_company":
        company = resolve_company(user, args.get("company_id"))
        if company is None:
            return {"error": "Aucune société à sélectionner."}
        if session_company_setter:
            session_company_setter(company)
        return {"ok": True, "company": company_card(company)}

    if company is None:
        return {"error": "Aucune société. Ajoutez un SIREN dans le cockpit."}

    if name == "get_company_overview":
        journals = list(company.journals.values_list("code", flat=True))
        accounts = list(company.accounts.order_by("code").values_list("code", "label")[:40])
        return {
            "company": company_card(company),
            "journals": journals,
            "accounts": [{"code": code, "label": label} for code, label in accounts],
        }

    if name == "get_balance":
        rows = balance_rows(company)
        return {"company": company.denomination, "rows": rows}

    if name == "list_entries":
        try:
            limit = int(args.get("limit") or 8)
        except (TypeError, ValueError):
            limit = 8
        limit = max(1, min(limit, 15))
        qs = JournalEntry.objects.filter(company=company, validated=True).select_related("journal")
        query = (args.get("query") or "").strip()
        if query:
            qs = qs.filter(label__icontains=query)
        entries = list(qs.order_by("-date", "-created_at")[:limit])
        return {"entries": [_entry_payload(entry) for entry in entries]}

    if name == "list_drafts":
        drafts = JournalEntry.objects.filter(
            company=company, validated=False, drafted_by_ai=True
        ).select_related("journal").order_by("-created_at")[:10]
        return {"drafts": [_entry_payload(entry) for entry in drafts]}

    if name == "propose_entry":
        return _propose_entry(company, args)

    if name == "confirm_entry":
        return _confirm_entry(company, args)

    if name == "draft_invoice":
        return _draft_invoice(company, args)

    if name == "draft_client":
        return _draft_client(company, args)

    return {"error": f"Outil inconnu : {name}"}


def _propose_entry(company, args):
    code = (args.get("journal") or "").strip().upper()
    journal = company.journals.filter(code=code).first()
    if journal is None:
        available = list(company.journals.values_list("code", flat=True))
        return {"error": f"Journal {code or 'vide'} absent.", "journals": available}

    raw_lines = args.get("lines") or []
    if len(raw_lines) < 2:
        return {"error": "Une écriture a au moins deux lignes."}

    parsed = []
    total_debit = Decimal("0.00")
    total_credit = Decimal("0.00")
    for raw in raw_lines:
        account = company.accounts.filter(code=str(raw.get("account_code") or "").strip()).first()
        if account is None:
            return {"error": f"Compte {raw.get('account_code')} inconnu pour cette société."}
        try:
            debit = money(raw.get("debit"))
            credit = money(raw.get("credit"))
        except ValueError:
            return {"error": "Montant illisible. Utilise des euros au centime."}
        if debit > 0 and credit > 0:
            return {"error": f"Le compte {account.code} ne peut pas être débit et crédit."}
        if debit < 0 or credit < 0:
            return {"error": "Montant négatif interdit."}
        if debit == 0 and credit == 0:
            return {"error": f"Ligne {account.code} vide."}
        total_debit += debit
        total_credit += credit
        parsed.append((account, debit, credit))

    if total_debit != total_credit:
        return {
            "error": "Écriture non équilibrée.",
            "debit": str(total_debit),
            "credit": str(total_credit),
        }

    raw_date = args.get("date") or date.today().isoformat()
    try:
        entry_date = date.fromisoformat(str(raw_date)[:10])
    except ValueError:
        return {"error": "Date invalide, format AAAA-MM-JJ."}

    label = (args.get("label") or "").strip()[:200]
    if not label:
        return {"error": "Libellé obligatoire."}

    with transaction.atomic():
        entry = JournalEntry.objects.create(
            company=company,
            journal=journal,
            date=entry_date,
            label=label,
            reference=(args.get("reference") or "")[:50],
            drafted_by_ai=True,
            validated=False,
        )
        for account, debit, credit in parsed:
            EntryLine.objects.create(entry=entry, account=account, debit=debit, credit=credit)

    return {
        "status": "brouillon",
        "message": "Brouillon créé. Relis les montants et attends un oui avant confirm_entry.",
        "entry": _entry_payload(entry),
    }


def _confirm_entry(company, args):
    if str(args.get("confirmation") or "").strip().lower() != "oui":
        return {"error": "Confirmation refusée. Il faut le mot oui après l'accord de l'utilisateur."}
    entry = JournalEntry.objects.filter(
        company=company, pk=args.get("entry_id"), drafted_by_ai=True
    ).first()
    if entry is None:
        return {"error": "Brouillon introuvable."}
    if entry.validated:
        return {"ok": True, "message": "Déjà validée.", "entry": _entry_payload(entry)}
    entry.validated = True
    entry.save(update_fields=["validated"])
    return {"ok": True, "message": "Écriture validée au grand livre.", "entry": _entry_payload(entry)}


def _draft_invoice(company, args):
    import uuid

    from documents.models import Invoice

    client = (args.get("client_name") or "").strip()
    if len(client) < 2:
        return {"error": "Nom du client manquant."}
    try:
        amount = money(args.get("amount_ht"))
    except ValueError:
        return {"error": "Montant HT illisible."}
    if amount <= 0:
        return {"error": "Le montant HT doit être positif."}
    siren = "".join(ch for ch in str(args.get("client_siren") or "") if ch.isdigit())
    if siren and len(siren) != 9:
        return {"error": "Le SIREN client doit contenir 9 chiffres, ou rester vide."}
    raw_rate = args.get("vat_rate")
    if raw_rate in (None, ""):
        rate = Decimal("20.00") if company.tva == "reel" else Decimal("0.00")
    else:
        try:
            rate = money(raw_rate)
        except ValueError:
            return {"error": "Taux de TVA illisible."}
    if rate < 0 or rate > 100:
        return {"error": "Taux de TVA invalide."}
    designation = (args.get("designation") or "Prestation").strip()[:200]
    invoice = Invoice.objects.create(
        company=company,
        number=f"BR-{uuid.uuid4().hex[:10]}",
        client_name=client[:200],
        client_siren=siren,
        amount_ht=amount,
        vat_rate=rate,
        status="draft",
    )
    return {
        "ok": True,
        "status": "brouillon",
        "message": "Brouillon affiché à l'écran. Il n'est pas émis.",
        "invoice": {
            "id": str(invoice.id),
            "number": invoice.number,
            "client_name": invoice.client_name,
            "client_siren": invoice.client_siren,
            "designation": designation,
            "amount_ht": str(invoice.amount_ht),
            "vat_rate": str(invoice.vat_rate),
            "amount_ttc": str(invoice.amount_ttc),
            "url": f"/factures/{invoice.id}/?societe={company.id}",
        },
    }


def _draft_client(company, args):
    """Crée un AiDraftEntry kind=client, jamais une fiche Client définitive."""
    from ai.models import AiDraftEntry

    name = (args.get("name") or "").strip()
    if len(name) < 2:
        return {"error": "Nom du client manquant."}
    siren = "".join(ch for ch in str(args.get("siren") or "") if ch.isdigit())
    if siren and len(siren) != 9:
        return {"error": "Le SIREN doit contenir 9 chiffres, ou rester vide."}
    email = (args.get("email") or "").strip()
    phone = (args.get("phone") or "").strip()
    address = (args.get("address") or "").strip()
    notes = (args.get("notes") or "").strip()
    payload = {
        "name": name[:200],
        "siren": siren,
        "email": email[:200],
        "phone": phone[:30],
        "address": address[:255],
        "notes": notes[:2000],
    }
    draft = AiDraftEntry.objects.create(
        company=company,
        kind="client",
        proposed_data=payload,
        proposed_lines=[],
        status="pending",
        model_name="aminia-voice",
    )
    return {
        "ok": True,
        "status": "brouillon",
        "message": (
            "Brouillon client créé. Il doit être validé par un humain "
            "dans Brouillons IA avant de créer la fiche."
        ),
        "draft": {
            "id": str(draft.id),
            "kind": "client",
            "status": draft.status,
            "data": payload,
            "url": f"/agent/brouillons/?societe={company.id}",
        },
    }

