"""Démo publique : seed de données et config de l'agent vocal Aminia.

Utilisé par le déploiement serverless (api/index.py) pour préparer un
cockpit de démonstration à chaque démarrage à froid, et pour exposer la
configuration SIP (poste appelé, WebRTC) au widget Aminia.
"""
import decimal
import os
from datetime import date

from django.conf import settings
from django.http import JsonResponse

from accounting.models import (
    ChartAccount,
    Journal,
    JournalEntry,
    EntryLine,
)
from accounting.services import generate_portal
from accounts.models import User
from companies.models import Company
from documents.models import Client, Invoice, InvoiceSeries, Product

DEMO_EMAIL = "demo@roadrunner-solutions.fr"
DEMO_SIREN = "812345678"
# Anciens bacs à sable jetables demo+...@demo.invalid : purgés au déploiement.
DEMO_SANDBOX_PREFIX = "demo+"
DEMO_SANDBOX_DOMAIN = "@demo.invalid"
# Compte d'administration (staff) : surchargeable via ADMIN_EMAIL.
# ADMIN_PASSWORD pose le premier mot de passe s'il n'y en a pas encore.
# Ensuite la connexion se fait par email + mot de passe, ou par lien de réinitialisation.
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@roadrunner-solutions.fr")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


def seed_admin():
    """Crée ou fiabilise le compte d'administration (is_staff) du back-office."""
    admin, created = User.objects.get_or_create(
        email=ADMIN_EMAIL,
        defaults={"is_staff": True, "is_superuser": True},
    )
    if created:
        admin.set_unusable_password()
        admin.save(update_fields=["password"])
    password = (ADMIN_PASSWORD or "").strip()
    if password and not admin.has_usable_password():
        admin.set_password(password)
        admin.save(update_fields=["password"])
    if not (admin.is_staff and admin.is_superuser):
        admin.is_staff = True
        admin.is_superuser = True
        admin.save(update_fields=["is_staff", "is_superuser"])
    return admin


def _demo_company_values():
    return {
        "denomination": "Menuiserie Dupont — SARL",
        "forme": "SARL",
        "address": "12 rue des Ateliers, 69003 Lyon",
        "code_naf": "43.32A",
        "activites": ["menuiserie"],
        "regime": "reel_simple",
        "tva": "reel",
        "exercice_debut": "2026-01-01",
    }


def _populate_demo_company(company):
    """Données fictives communes au compte de démo et aux bacs à sable."""
    generate_portal(company)

    def account(code, label):
        return ChartAccount.objects.get_or_create(
            company=company, code=code, defaults={"label": label}
        )[0]

    a411 = account("411", "Clients")
    a44571 = account("44571", "TVA collectée")
    a706 = account("706", "Ventes de services")
    a401 = account("401", "Fournisseurs")
    a6063 = account("6063", "Achats non stockés de matières")
    a512 = account("512", "Banque")
    jv = Journal.objects.get_or_create(
        company=company, code="VEN", defaults={"name": "Journal des ventes", "type": "ventes"}
    )[0]
    ja = Journal.objects.get_or_create(
        company=company, code="ACH", defaults={"name": "Journal des achats", "type": "achats"}
    )[0]
    jb = Journal.objects.get_or_create(
        company=company, code="BQ", defaults={"name": "Journal de banque", "type": "banque"}
    )[0]

    def entry(journal, date, label, ref, lines, validated=True):
        if JournalEntry.objects.filter(company=company, reference=ref, label=label).exists():
            return None
        e = JournalEntry.objects.create(
            company=company, journal=journal, date=date, label=label,
            reference=ref, validated=validated,
        )
        for acc, d, c in lines:
            EntryLine.objects.create(
                entry=e, account=acc,
                debit=decimal.Decimal(d), credit=decimal.Decimal(c),
            )
        return e

    entry(jv, "2026-10-12", "Facture Cadres Industries", "FAC-2026-00042",
          [(a411, "2880.00", "0.00"), (a706, "0.00", "2400.00"), (a44571, "0.00", "480.00")])
    entry(ja, "2026-10-20", "Achat outillage", "FAC Fournisseur",
          [(a6063, "1240.00", "0.00"), (a401, "0.00", "1240.00")])
    entry(jb, "2026-10-25", "Encaissement Cadres Industries", "FAC-2026-00042",
          [(a512, "2880.00", "0.00"), (a411, "0.00", "2880.00")])

    client_cadres, _ = Client.objects.get_or_create(
        company=company,
        name="Cadres Industries",
        defaults={
            "siren": "552100554",
            "email": "contact@cadres-industries.example",
            "address": "8 avenue des Arts, 69002 Lyon",
        },
    )
    Client.objects.get_or_create(
        company=company,
        name="Atelier Martin",
        defaults={
            "email": "atelier.martin@example.invalid",
            "address": "3 rue des Meuniers, 69007 Lyon",
        },
    )
    Product.objects.get_or_create(
        company=company,
        label="Pose de fenêtre",
        defaults={
            "description": "Fourniture et pose d'une fenêtre PVC double vitrage.",
            "unit_price": decimal.Decimal("250.00"),
            "vat_rate": decimal.Decimal("20.00"),
            "unit": "unité",
        },
    )
    Product.objects.get_or_create(
        company=company,
        label="Déplacement chantier",
        defaults={
            "description": "Déplacement et préparation du chantier.",
            "unit_price": decimal.Decimal("45.00"),
            "vat_rate": decimal.Decimal("10.00"),
            "unit": "forfait",
        },
    )

    series, _ = InvoiceSeries.objects.get_or_create(
        company=company,
        year=2026,
        prefix="FAC",
        defaults={"last_number": 43},
    )
    if series.last_number < 43:
        series.last_number = 43
        series.save(update_fields=["last_number"])
    Invoice.objects.get_or_create(
        company=company,
        number="FAC-2026-00042",
        defaults=dict(
            client=client_cadres,
            client_name="Cadres Industries",
            client_siren="552100554",
            amount_ht=decimal.Decimal("2400.00"),
            vat_rate=decimal.Decimal("20.00"),
            status="paid",
        ),
    )
    Invoice.objects.get_or_create(
        company=company,
        number="FAC-2026-00043",
        defaults=dict(
            client_name="Atelier Martin",
            amount_ht=decimal.Decimal("800.00"),
            vat_rate=decimal.Decimal("20.00"),
            status="issued",
        ),
    )
    from documents.services import pay_invoice

    martin = Invoice.objects.get(company=company, number="FAC-2026-00043")
    if martin.status != "paid":
        pay_invoice(martin)

    # --- Achats fournisseurs -------------------------------------------------
    from mailsync.models import MailboxConfig, Supplier
    from purchases.models import PurchaseInvoice
    from purchases.services import PurchaseError, post_purchase

    supplier, _ = Supplier.objects.get_or_create(
        company=company,
        name="Quincaillerie Rhône",
        defaults={
            "email": "contact@quincaillerie-rhone.example",
            "email_domain": "quincaillerie-rhone.example",
            "siret": "73282932000074",
            "tva_intra": "FR44732829320",
            "payment_terms_days": 30,
            "default_charge_code": "6063",
            "address": "45 rue de la Villette, 69003 Lyon",
        },
    )
    purchase, _ = PurchaseInvoice.objects.get_or_create(
        company=company,
        supplier=supplier,
        number="ACH-2026-0007",
        defaults={
            "supplier_name": supplier.name,
            "invoice_date": date(2026, 10, 20),
            "due_date": date(2026, 11, 20),
            "amount_ht": decimal.Decimal("1240.00"),
            "amount_vat": decimal.Decimal("248.00"),
            "amount_ttc": decimal.Decimal("1488.00"),
            "charge_account_code": "6063",
            "vat_account_code": "44566",
            "supplier_account_root": "401",
            "description": "Outillage et quincaillerie",
            "status": "draft",
        },
    )
    if purchase.status == "draft":
        try:
            post_purchase(purchase)
        except PurchaseError:
            pass

    # --- Banque --------------------------------------------------------------
    from banking.models import BankAccount, BankStatement, BankTransaction

    bank, _ = BankAccount.objects.get_or_create(
        company=company,
        label="Compte principal",
        defaults={
            "bank_name": "Crédit Lyonnais",
            "iban": "FR7610278060410002063428704",
            "bic": "CMCIFR2A",
            "journal": jb,
            "ledger_account": a512,
        },
    )
    if not bank.ledger_account_id:
        bank.ledger_account = a512
        bank.save(update_fields=["ledger_account"])

    statement, _ = BankStatement.objects.get_or_create(
        company=company,
        account=bank,
        original_filename="demo-releve.csv",
        defaults={
            "date_start": date(2026, 10, 1),
            "date_end": date(2026, 10, 31),
            "source_format": "csv",
            "row_count": 2,
        },
    )
    matched_entry = JournalEntry.objects.filter(
        company=company, journal__code="BQ", reference="FAC-2026-00042"
    ).first()
    BankTransaction.objects.get_or_create(
        company=company,
        account=bank,
        fingerprint="demo-bank-001",
        defaults={
            "statement": statement,
            "date": date(2026, 10, 25),
            "label": "VIR CLIENT CADRES INDUSTRIES",
            "counterparty": "Cadres Industries",
            "reference": "FAC-2026-00042",
            "amount": decimal.Decimal("2880.00"),
            "status": "matched" if matched_entry else "unmatched",
            "matched_entry": matched_entry,
            "match_type": "auto" if matched_entry else "",
            "match_score": 90 if matched_entry else 0,
        },
    )
    BankTransaction.objects.get_or_create(
        company=company,
        account=bank,
        fingerprint="demo-bank-002",
        defaults={
            "statement": statement,
            "date": date(2026, 10, 28),
            "label": "FRAIS BANCAIRES",
            "amount": decimal.Decimal("-12.50"),
            "status": "unmatched",
        },
    )

    # --- Connecteur e-mail (configuration visible, non connectée) -----------
    MailboxConfig.objects.get_or_create(
        company=company,
        defaults={
            "provider": "gmail",
            "is_active": False,
            "folder_label": "Factures fournisseurs",
            "charge_account_code": "6063",
            "vat_account_code": "44566",
            "supplier_account_root": "401",
        },
    )
    return company


def seed_demo():
    """Idempotent : crée l'utilisateur, la société de démo et son portail comptable."""
    seed_admin()
    user, _ = User.objects.get_or_create(email=DEMO_EMAIL)
    company, _ = Company.objects.get_or_create(
        siren=DEMO_SIREN,
        defaults={"owner": user, **_demo_company_values()},
    )
    _populate_demo_company(company)
    return user, company


def _delete_sandbox_users(user_ids):
    """Supprime des comptes de démo sans buter sur JournalEntry.journal PROTECT."""
    if not user_ids:
        return
    companies = Company.objects.filter(owner_id__in=user_ids)
    JournalEntry.objects.filter(company__in=companies).delete()
    companies.delete()
    User.objects.filter(pk__in=user_ids).delete()


def purge_demo_sandboxes() -> int:
    """Supprime tous les anciens comptes demo+...@demo.invalid.

    Appelé au déploiement et à l'ouverture de la démo pour nettoyer les
    comptes créés par l'ancien système de bac à sable par visiteur.
    """
    user_ids = list(
        User.objects.filter(
            email__istartswith=DEMO_SANDBOX_PREFIX,
            email__iendswith=DEMO_SANDBOX_DOMAIN,
        ).values_list("pk", flat=True)
    )
    _delete_sandbox_users(user_ids)
    return len(user_ids)


def purge_extra_demo_companies() -> int:
    """Ne garde qu'une société pour le compte démo fixe.

    Les anciennes visites pouvaient créer d'autres sociétés dans le compte
    partagé. On supprime tout ce qui n'est pas la société de démonstration
    officielle (SIREN DEMO_SIREN).
    """
    user = User.objects.filter(email=DEMO_EMAIL).first()
    if user is None:
        return 0
    extras = list(user.companies.exclude(siren=DEMO_SIREN))
    for company in extras:
        JournalEntry.objects.filter(company=company).delete()
        company.delete()
    return len(extras)


def exclude_demo_users(queryset):
    """Retire le compte démo et les anciens bacs à sable des listes admin."""
    return queryset.exclude(email__iendswith=DEMO_SANDBOX_DOMAIN).exclude(
        email__iexact=DEMO_EMAIL
    )


def demo_login(request):
    """Ouvre la démo publique en lecture seule.

    Un seul compte et une seule société de démonstration sont utilisés :
    aucune donnée n'est créée par visiteur, et les écritures sont bloquées
    par DemoModeMiddleware. Les anciens bacs à sable sont purgés ici.
    """
    from django.contrib.auth import login, logout
    from django.shortcuts import redirect
    from django.urls import reverse

    if request.user.is_authenticated and request.user.email != DEMO_EMAIL:
        logout(request)

    if User.objects.filter(
        email__istartswith=DEMO_SANDBOX_PREFIX,
        email__iendswith=DEMO_SANDBOX_DOMAIN,
    ).exists():
        purge_demo_sandboxes()
    purge_extra_demo_companies()

    user, company = seed_demo()
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session["societe_id"] = str(company.id)
    request.session["demo_mode"] = True
    # Pas de message flash : le bandeau "demo-readonly-banner" de base.html
    # affiche déjà l'information en permanence (un flash doublait chaque page).

    nxt = request.GET.get("next") or reverse("cockpit")
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = reverse("cockpit")
    separator = "&" if "?" in nxt else "?"
    return redirect(f"{nxt}{separator}societe={company.id}")


def agent_config(request):
    """Configuration SIP/WebRTC du widget Aminia (même origine uniquement)."""
    origin = request.headers.get("Origin", "")
    if origin and origin != request.scheme + "://" + request.get_host():
        return JsonResponse({"error": "forbidden"}, status=403)
    if not settings.VOICE_SIP_HOST:
        return JsonResponse({"error": "not_configured"}, status=503)
    # Utilisation du domaine vocalia-solutions.com pour le certificat SSL Let's Encrypt
    # au lieu de l'adresse IP qui ne est pas couverte par le certificat
    sip_host = settings.VOICE_SIP_HOST
    if sip_host == "213.156.135.132":
        sip_host = "vocalia-solutions.com"
    return JsonResponse({
        "agent": settings.VOICE_AGENT_NAME,
        "sip": {
            "host": sip_host,
            "ext": settings.VOICE_SIP_EXT,
            "user": settings.VOICE_SIP_USER,
            "password": settings.VOICE_SIP_PASSWORD,
            "callee": settings.VOICE_SIP_CALLEE,
            "wss": [
                f"wss://{sip_host}/ws",
                f"wss://{sip_host}/ws",
            ],
        },
    })
