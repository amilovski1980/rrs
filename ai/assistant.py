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
    from documents.models import Product

    products = list(company.products.filter(active=True).order_by("label")[:40])
    if products:
        catalogue = "; ".join(
            f"{p.label} ({p.unit_price:.2f} € HT, TVA {p.vat_rate:g} %, id {p.id})"
            for p in products
        )
        extra += (
            " Catalogue produits de la société, à utiliser en priorité pour les lignes "
            f"de facture : {catalogue}. Quand un produit correspond, transmets son id "
            "dans draft_invoice (champ lines[].product_id)."
        )
    else:
        extra += (
            " Le catalogue produits est vide : utilise une désignation libre pour "
            "les lignes de facture."
        )
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


def admin_context_for(user, company, *, channel: str = "voice") -> str:
    """Contexte du personnel : pas de rôle d'assistante comptable client.

    Le personnel garde les outils du cockpit pour vérifier une société, mais
    la consigne administrateur ne doit pas être noyée par un contexte métier.
    """
    mode = "chat texte" if channel == "chat" else "voix"
    if company is None:
        return (
            "Contexte administrateur : aucune société n'est sélectionnée. "
            f"Tu es connecté en mode {mode} pour le personnel. "
            "Tu peux expliquer une procédure, inspecter la configuration accessible "
            "et proposer une correction. N'invente aucun chiffre et ne présente "
            "aucune donnée client."
        )
    return (
        "Contexte administrateur : tu es connecté au cockpit en mode "
        f"{mode}, avec la société de test {company.denomination} "
        f"(SIREN {company.siren}). Cette société sert à vérifier les écrans et les outils. "
        "Tu n'es pas son assistante comptable et tu ne te présentes pas comme telle. "
        "N'utilise ses données que si la tâche le demande explicitement."
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
            "Rédige un brouillon de facture avec une ou plusieurs lignes. À appeler dès "
            "que le client et les montants sont connus. Utilise de préférence un produit "
            "du catalogue via lines[].product_id. N'émet pas la facture."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "client_name": {"type": "string", "description": "Nom du client"},
                "client_siren": {"type": "string", "description": "SIREN à 9 chiffres, ou vide"},
                "amount_ht": {
                    "type": "string",
                    "description": "Montant HT total, si aucune ligne détaillée n'est fournie",
                },
                "vat_rate": {"type": "string", "description": "Taux de TVA, par exemple 20 ou 0"},
                "designation": {"type": "string", "description": "Libellé de la prestation"},
                "lines": {
                    "type": "array",
                    "description": "Lignes détaillées de la facture",
                    "items": {
                        "type": "object",
                        "properties": {
                            "product_id": {
                                "type": "string",
                                "description": "Identifiant UUID d'un produit du catalogue",
                            },
                            "description": {"type": "string", "description": "Désignation de la ligne"},
                            "quantity": {"type": "string", "description": "Quantité, 1 par défaut"},
                            "unit_price": {"type": "string", "description": "Prix unitaire HT en euros"},
                            "vat_rate": {"type": "string", "description": "Taux de TVA de la ligne"},
                        },
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["client_name"],
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
    {
        "type": "function",
        "name": "search_french_companies",
        "description": (
            "Recherche une entreprise française dans l'annuaire officiel par nom, "
            "SIREN à 9 chiffres ou SIRET à 14 chiffres (dictés chiffre par chiffre), "
            "avec ville ou code postal facultatifs. Un panneau numéroté s'affiche : "
            "annonce le nombre de résultats et invite à en choisir un (« la deuxième »). "
            "N'invente jamais une entreprise si aucun résultat."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Nom de l'entreprise, ou SIREN/SIRET en chiffres",
                },
                "city": {"type": "string", "description": "Ville de l'établissement, facultatif"},
                "postal_code": {"type": "string", "description": "Code postal à 5 chiffres, facultatif"},
                "limit": {"type": "integer", "description": "Nombre de fiches à afficher, 1 à 10, 5 par défaut"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "choose_company_result",
        "description": (
            "Sélectionne une fiche du dernier panneau de résultats, d'après le numéro "
            "dicté (« la deuxième » vaut index 2). Demande ensuite une confirmation "
            "avant toute création de client, fournisseur ou facture."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "index": {"type": "integer", "description": "Numéro du résultat affiché, 1 à 10"},
                "siren": {"type": "string", "description": "SIREN à 9 chiffres si l'index est inconnu"},
            },
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "update_draft_invoice",
        "description": (
            "Modifie un brouillon de facture déjà créé : client, SIREN, montant HT, "
            "taux de TVA ou désignation de la prestation. Relis ensuite les valeurs "
            "modifiées à voix haute, champs par champs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "invoice_id": {"type": "string", "description": "Identifiant du brouillon à modifier"},
                "client_name": {"type": "string", "description": "Nom du client, ou vide"},
                "client_siren": {"type": "string", "description": "SIREN à 9 chiffres, ou vide"},
                "amount_ht": {"type": "string", "description": "Montant HT de la prestation"},
                "vat_rate": {"type": "string", "description": "Taux de TVA, par exemple 20"},
                "designation": {"type": "string", "description": "Libellé de la prestation"},
            },
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


def execute_tool(user, company, name, args, session_company_setter=None, session=None):
    args = args or {}
    from admin_backoffice.agent_prompts import tool_allowed

    if not tool_allowed(user, name):
        return {"error": "Cette action n'est pas incluse dans votre forfait."}
    from billing.access import feature_on, invoice_create_block

    tool_feature = {
        "draft_invoice": "invoices",
        "draft_client": "clients",
        "propose_entry": "entries",
        "confirm_entry": "entries",
        "get_balance": "balance",
        "list_entries": "ledger",
    }.get(name)
    if tool_feature and not feature_on(user, tool_feature):
        return {"error": "Cette action n'est pas incluse dans votre forfait."}
    if name == "draft_invoice":
        block = invoice_create_block(user)
        if block:
            return {"error": block}
    if name == "list_companies":
        return {"companies": [company_card(c) for c in owned_companies(user)]}

    if name == "switch_company":
        company = resolve_company(user, args.get("company_id"))
        if company is None:
            return {"error": "Aucune société à sélectionner."}
        if session_company_setter:
            session_company_setter(company)
        return {"ok": True, "company": company_card(company)}

    if name == "search_french_companies":
        return _search_french_companies(user, company, args, session)

    if name == "choose_company_result":
        return _choose_company_result(user, company, args, session)

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

    if name == "update_draft_invoice":
        from billing.access import feature_on, invoice_create_block as _ivb

        block = _ivb(user)
        if block or not feature_on(user, "invoices"):
            return {"error": "Cette action n'est pas incluse dans votre forfait."}
        return _update_draft_invoice(company, args)

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

    from documents.models import Invoice, InvoiceLine, Product

    client = (args.get("client_name") or "").strip()
    if len(client) < 2:
        return {"error": "Nom du client manquant."}
    siren = "".join(ch for ch in str(args.get("client_siren") or "") if ch.isdigit())
    if siren and len(siren) != 9:
        return {"error": "Le SIREN client doit contenir 9 chiffres, ou rester vide."}

    def default_rate():
        return Decimal("20.00") if company.tva == "reel" else Decimal("0.00")

    def parse_rate(raw):
        if raw in (None, ""):
            return default_rate()
        rate_value = money(raw)
        if rate_value < 0 or rate_value > 100:
            raise ValueError("Taux de TVA invalide.")
        return rate_value

    prepared = []
    raw_lines = args.get("lines")
    if isinstance(raw_lines, list) and raw_lines:
        for raw in raw_lines[:50]:
            if not isinstance(raw, dict):
                continue
            product = None
            product_id = str(raw.get("product_id") or "").strip()
            if product_id:
                product = Product.objects.filter(
                    company=company, active=True, pk=product_id
                ).first()
                if product is None:
                    return {"error": "Produit du catalogue introuvable pour cette société."}
            description = (
                (raw.get("description") or "").strip()
                or (product.label if product else "")
                or "Prestation"
            )[:200]
            try:
                quantity = money(raw.get("quantity") or "1")
                unit_price = money(
                    raw.get("unit_price")
                    if raw.get("unit_price") not in (None, "")
                    else (product.unit_price if product else "0")
                )
                rate = parse_rate(
                    raw.get("vat_rate")
                    if raw.get("vat_rate") not in (None, "")
                    else (product.vat_rate if product else None)
                )
            except ValueError as exc:
                return {"error": str(exc) or "Ligne de facture illisible."}
            if quantity <= 0:
                return {"error": "La quantité doit être supérieure à 0."}
            if unit_price < 0:
                return {"error": "Le prix unitaire ne peut pas être négatif."}
            prepared.append({
                "product": product,
                "description": description,
                "quantity": quantity,
                "unit_price": unit_price,
                "vat_rate": rate,
            })
    else:
        try:
            amount = money(args.get("amount_ht"))
            rate = parse_rate(args.get("vat_rate"))
        except ValueError:
            return {"error": "Montant HT illisible."}
        if amount <= 0:
            return {"error": "Le montant HT doit être positif."}
        prepared.append({
            "product": None,
            "description": (args.get("designation") or "Prestation").strip()[:200],
            "quantity": Decimal("1"),
            "unit_price": amount,
            "vat_rate": rate,
        })

    if not prepared:
        return {"error": "Ajoutez au moins une ligne à la facture."}

    total_ht = sum(
        (line["quantity"] * line["unit_price"] for line in prepared), Decimal("0.00")
    ).quantize(Decimal("0.01"))
    if total_ht <= 0:
        return {"error": "Le montant HT doit être positif."}
    bases: dict[Decimal, Decimal] = {}
    for line in prepared:
        bases[line["vat_rate"]] = bases.get(line["vat_rate"], Decimal("0.00")) + (
            line["quantity"] * line["unit_price"]
        )
    dominant_rate = max(bases, key=bases.get)

    with transaction.atomic():
        invoice = Invoice.objects.create(
            company=company,
            number=f"BR-{uuid.uuid4().hex[:10]}",
            client_name=client[:200],
            client_siren=siren,
            amount_ht=total_ht,
            vat_rate=dominant_rate,
            status="draft",
        )
        for position, line in enumerate(prepared):
            InvoiceLine.objects.create(
                invoice=invoice,
                product=line["product"],
                description=line["description"],
                quantity=line["quantity"],
                unit_price=line["unit_price"],
                vat_rate=line["vat_rate"],
                position=position,
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
            "designation": prepared[0]["description"],
            "amount_ht": str(invoice.amount_ht),
            "vat_rate": str(invoice.vat_rate),
            "amount_ttc": str(invoice.amount_ttc),
            "lines": [
                {
                    "product_id": str(line["product"].id) if line["product"] else "",
                    "description": line["description"],
                    "quantity": str(line["quantity"]),
                    "unit_price": str(line["unit_price"]),
                    "vat_rate": str(line["vat_rate"]),
                }
                for line in prepared
            ],
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


def _search_french_companies(user, company, args, session=None):
    """Recherche l'annuaire officiel et numérote les fiches pour l'écran."""
    from documents.models import Client
    from integrations.insee import search_french_companies
    from suppliers.models import Supplier

    query = " ".join(str(args.get("query") or "").split())
    if not query:
        return {"error": "Indiquez le nom de l'entreprise, ou son SIREN ou SIRET."}
    try:
        limit = int(args.get("limit") or 5)
    except (TypeError, ValueError):
        limit = 5
    results, error, retry_after, geo_applied = search_french_companies(
        query,
        city=str(args.get("city") or ""),
        postal_code=str(args.get("postal_code") or ""),
        limit=limit,
    )
    if error == "rate_limit":
        return {
            "error": "L'annuaire officiel est momentanément saturé : réessayez dans une minute.",
            "retry_after_seconds": retry_after or 60,
        }
    if error == "invalid":
        return {"error": "Requête invalide : donnez un nom, un SIREN à 9 chiffres ou un SIRET."}
    if error:
        return {"error": "L'annuaire officiel (recherche-entreprises.api.gouv.fr) est indisponible."}
    if not results:
        return {
            "results": [],
            "message": (
                "Aucune entreprise ne correspond à cette recherche. L'absence de résultat "
                "ne prouve pas que l'entreprise n'existe pas : reformulez ou vérifiez le SIREN."
            ),
        }

    # Anti-doublon : fiche déjà rattachée à la société courante.
    sirens = [item["siren"] for item in results]
    sirets = [item["siret"] for item in results if item.get("siret")]
    client_sirens: set[str] = set()
    supplier_sirets: set[str] = set()
    if company is not None:
        client_sirens = set(
            Client.objects.filter(company=company, siren__in=sirens).values_list("siren", flat=True)
        )
        if sirets:
            supplier_sirets = set(
                Supplier.objects.filter(company=company, siret__in=sirets).values_list("siret", flat=True)
            )
    for item in results:
        item["deja_client"] = item["siren"] in client_sirens
        item["deja_fournisseur"] = item.get("siret", "") in supplier_sirets

    # Mémoire légère en session : numéro -> (siren, siret) pour « la deuxième ».
    if session is not None:
        try:
            session["aminia_results"] = {
                str(item["index"]): {"siren": item["siren"], "siret": item.get("siret", "")}
                for item in results
            }
        except Exception:
            pass  # la session est un cookie : on ne bloque jamais la recherche

    return {
        "results": results,
        "count": len(results),
        "geo_filtre": geo_applied,
        "company": {"id": str(company.id), "denomination": company.denomination} if company else None,
    }


def _choose_company_result(user, company, args, session=None):
    """Sélection « la deuxième » / « la 2 » : fiche complète + drapeaux doublon."""
    from documents.models import Client
    from integrations.insee import official_card
    from suppliers.models import Supplier

    memory = {}
    if session is not None:
        try:
            memory = session.get("aminia_results") or {}
        except Exception:
            memory = {}
    try:
        index = int(args.get("index"))
    except (TypeError, ValueError):
        index = None
    siren = "".join(ch for ch in str(args.get("siren") or "") if ch.isdigit())

    mem = memory.get(str(index)) if index is not None else None
    if mem:
        siren = str(mem.get("siren") or "")
        siret = str(mem.get("siret") or "")
    elif siren:
        siret = ""
    else:
        return {"error": "Indiquez le numéro du résultat (« la deuxième » = 2) ou son SIREN."}
    if len(siren) != 9:
        return {"error": "SIREN invalide (9 chiffres attendus)."}

    card, error = official_card(siren)
    if error == "rate_limit":
        return {"error": "L'annuaire officiel est momentanément saturé : réessayez dans une minute."}
    if error == "empty" or error == "not_found":
        return {"error": "Aucune entreprise valide sur ce SIREN : relancez la recherche."}
    if error or not card:
        return {"error": "Le service annuaire est indisponible : relancez la recherche."}

    siret = siret or str(card.get("siret") or "")
    already_client = False
    already_supplier = False
    if company is not None:
        already_client = Client.objects.filter(company=company, siren=siren).exists()
        if siret:
            already_supplier = Supplier.objects.filter(company=company, siret=siret).exists()

    if session is not None:
        try:
            session["aminia_picked"] = {
                "index": index,
                "siren": siren,
                "siret": siret,
                "denomination": str(card.get("denomination") or "")[:120],
                "adresse": str(card.get("adresse") or "")[:160],
            }
        except Exception:
            pass

    return {
        "selected": {
            "index": index,
            "siren": siren,
            "siret": siret,
            "denomination": card.get("denomination", ""),
            "forme": card.get("forme", ""),
            "adresse": card.get("adresse", ""),
            "ville": card.get("ville", ""),
            "code_postal": card.get("code_postal", ""),
            "naf": card.get("naf", ""),
            "etat": card.get("etat", ""),
            "deja_client": already_client,
            "deja_fournisseur": already_supplier,
        }
    }


def _update_draft_invoice(company, args):
    """Modifie un brouillon de facture existant (client, montant, TVA, désignation).

    L'utilisateur peut aussi corriger depuis le panneau Aminia : les deux écritures
    (outil et édition manuelle) passent par le même recompute des totaux.
    """
    from documents.models import Invoice, InvoiceLine

    invoice_id = str(args.get("invoice_id") or "").strip()
    invoice = None
    if invoice_id:
        invoice = Invoice.objects.filter(pk=invoice_id, company=company).first()
    if invoice is None:
        invoice = (
            Invoice.objects.filter(company=company, status="draft")
            .order_by("-created_at")
            .first()
        )
    if invoice is None:
        return {"error": "Aucun brouillon de facture à modifier."}

    changed = []
    client_name = (args.get("client_name") or "").strip()
    if client_name and client_name != (invoice.client_name or ""):
        invoice.client_name = client_name[:200]
        changed.append("client : " + client_name[:80])

    siren = "".join(ch for ch in str(args.get("client_siren") or "") if ch.isdigit())
    if siren and len(siren) == 9 and siren != (invoice.client_siren or ""):
        invoice.client_siren = siren
        changed.append("SIREN : " + siren)

    vat_rate_changed = False
    from decimal import InvalidOperation as _Invalid
    vat_raw = str(args.get("vat_rate") or "").replace(",", ".").strip()
    vat_rate = None
    if vat_raw:
        try:
            vat_rate = Decimal(vat_raw).quantize(Decimal("0.01"))
        except (_Invalid, ValueError):
            vat_rate = None
        if vat_rate is not None and 0 <= vat_rate <= 100 and vat_rate != invoice.vat_rate:
            invoice.vat_rate = vat_rate
            vat_rate_changed = True
            changed.append(f"TVA : {vat_rate} %")

    amount = str(args.get("amount_ht") or "").replace(",", ".").strip()
    ht = None
    if amount:
        try:
            ht = Decimal(amount).quantize(Decimal("0.01"))
        except (_Invalid, ValueError):
            ht = None
    designation = (args.get("designation") or "").strip()

    line = invoice.lines.first() if invoice.pk else None
    if ht is not None:
        if line is None:
            line = InvoiceLine(
                invoice=invoice, quantity=Decimal("1.000"), unit_price=ht,
            )
        else:
            line.unit_price = ht
            if line.quantity is None:
                line.quantity = Decimal("1.000")
            changed.append(f"Montant HT : {ht}")
    if line is not None and designation and designation != (line.description or ""):
        line.description = designation[:255]
        changed.append("prestation : " + designation[:60])
    if line is not None and vat_rate is not None and vat_rate_changed:
        line.vat_rate = vat_rate

    if not changed:
        return {"error": "Aucune modification fournie."}

    if line is not None:
        line.save()
    invoice.save()
    from documents.services import recompute_invoice_totals_from_lines

    recompute_invoice_totals_from_lines(invoice)
    invoice.refresh_from_db()

    return {
        "ok": True,
        "changed": changed or ["Déjà à jour."],
        "invoice": {
            "id": str(invoice.id),
            "number": invoice.number,
            "url": f"/factures/{invoice.id}/?societe={company.id}",
            "client_name": invoice.client_name,
            "client_siren": invoice.client_siren,
            "amount_ht": str(invoice.amount_ht),
            "vat_amount": str(invoice.vat_amount),
            "vat_rate": str(invoice.vat_rate),
            "amount_ttc": str(invoice.amount_ttc),
            "status": invoice.get_status_display(),
        },
    }

