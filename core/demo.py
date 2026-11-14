"""Démo publique : seed de données et config de l'agent vocal Aminia.

Utilisé par le déploiement serverless (api/index.py) pour préparer un
cockpit de démonstration à chaque démarrage à froid, et pour exposer la
configuration SIP (poste appelé, WebRTC) au widget Aminia.
"""
import decimal
import os
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone

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
# Comptes de démonstration jetables : un par visiteur, supprimés après 12 h.
DEMO_SANDBOX_PREFIX = "demo+"
DEMO_SANDBOX_DOMAIN = "@demo.invalid"
DEMO_SANDBOX_HOURS = 12
DEMO_SANDBOX_MAX = 120
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


def _is_sandbox_user(user) -> bool:
    email = (getattr(user, "email", "") or "").lower()
    return email.startswith(DEMO_SANDBOX_PREFIX) and email.endswith(DEMO_SANDBOX_DOMAIN)


def _delete_sandbox_users(user_ids):
    """Supprime des comptes de démo sans buter sur JournalEntry.journal PROTECT."""
    if not user_ids:
        return
    companies = Company.objects.filter(owner_id__in=user_ids)
    JournalEntry.objects.filter(company__in=companies).delete()
    companies.delete()
    User.objects.filter(pk__in=user_ids).delete()


def _cleanup_sandboxes():
    """Supprime les bacs à sable expirés et limite le stock total."""
    cutoff = timezone.now() - timedelta(hours=DEMO_SANDBOX_HOURS)
    sandboxes = User.objects.filter(
        email__istartswith=DEMO_SANDBOX_PREFIX,
        email__iendswith=DEMO_SANDBOX_DOMAIN,
    )
    stale = list(
        sandboxes.filter(created_at__lt=cutoff).values_list("pk", flat=True)
    )
    _delete_sandbox_users(stale)
    remaining = list(sandboxes.order_by("-created_at").values_list("pk", flat=True))
    if len(remaining) > DEMO_SANDBOX_MAX:
        _delete_sandbox_users(remaining[DEMO_SANDBOX_MAX:])


def _sandbox_siren() -> str:
    for _attempt in range(30):
        candidate = f"9{secrets.randbelow(100_000_000):08d}"
        if not Company.objects.filter(siren=candidate).exists():
            return candidate
    raise RuntimeError("Impossible de créer un SIREN de démonstration.")


def _create_sandbox():
    _cleanup_sandboxes()
    with transaction.atomic():
        user = User(
            email=f"{DEMO_SANDBOX_PREFIX}{uuid.uuid4().hex[:12]}{DEMO_SANDBOX_DOMAIN}",
            first_name="Visiteur",
            last_name="Démo",
        )
        user.set_unusable_password()
        user.save()
        company = Company.objects.create(
            owner=user,
            siren=_sandbox_siren(),
            **_demo_company_values(),
        )
        _populate_demo_company(company)
    return user, company


def _sandbox_for_session(request):
    user_id = request.session.get("demo_sandbox_id")
    if user_id:
        user = User.objects.filter(pk=user_id).first()
        if user and _is_sandbox_user(user):
            company = user.companies.order_by("created_at").first()
            if company is not None:
                return user, company
    user, company = _create_sandbox()
    request.session["demo_sandbox_id"] = str(user.id)
    return user, company


def demo_login(request):
    """Ouvre une démo isolée par visiteur, sans partager le compte de démo.

    Chaque session reçoit sa propre société fictive. Les visiteurs peuvent
    créer, modifier et émettre des factures sans toucher aux données des autres.
    """
    from django.contrib import messages
    from django.contrib.auth import login, logout
    from django.shortcuts import redirect
    from django.urls import reverse

    if request.user.is_authenticated and not _is_sandbox_user(request.user):
        logout(request)

    user, company = _sandbox_for_session(request)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session["societe_id"] = str(company.id)
    request.session["demo_mode"] = True
    messages.info(
        request,
        "Mode démo : cette société, ses clients et ses factures sont propres à "
        "votre session. Ils seront supprimés automatiquement.",
    )

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
