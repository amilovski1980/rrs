"""Démo publique : seed de données et config de l'agent vocal Aminia.

Utilisé par le déploiement serverless (api/index.py) pour préparer un
cockpit de démonstration à chaque démarrage à froid, et pour exposer la
configuration SIP (poste appelé, WebRTC) au widget Aminia.
"""
import decimal
import os

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
from documents.models import Invoice, InvoiceSeries

DEMO_EMAIL = "demo@roadrunner-solutions.fr"
DEMO_SIREN = "812345678"
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


def seed_demo():
    """Idempotent : crée l'utilisateur, la société de démo et son portail comptable."""
    seed_admin()
    user, _ = User.objects.get_or_create(email=DEMO_EMAIL)
    company, created = Company.objects.get_or_create(
        siren=DEMO_SIREN,
        defaults=dict(
            owner=user,
            denomination="Menuiserie Dupont — SARL",
            forme="SARL",
            address="12 rue des Ateliers, 69003 Lyon",
            code_naf="43.32A",
            activites=["menuiserie"],
            regime="reel_simple",
            tva="reel",
            exercice_debut="2026-01-01",
        ),
    )
    if created:
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
        number="FAC-2026-00042",
        defaults=dict(
            company=company, client_name="Cadres Industries", client_siren="552100554",
            amount_ht=decimal.Decimal("2400.00"), vat_rate=decimal.Decimal("20.00"),
            status="paid",
        ),
    )
    Invoice.objects.get_or_create(
        number="FAC-2026-00043",
        defaults=dict(
            company=company, client_name="Atelier Martin",
            amount_ht=decimal.Decimal("800.00"), vat_rate=decimal.Decimal("20.00"),
            status="issued",
        ),
    )
    from documents.services import pay_invoice

    martin = Invoice.objects.get(number="FAC-2026-00043")
    if martin.status != "paid":
        pay_invoice(martin)
    return user, company


def demo_login(request):
    """Connexion automatique : ouvre le cockpit de démonstration sans email.

    Réservé au compte de démonstration qui ne contient que des données fictives.
    """
    from django.contrib.auth import login
    from django.shortcuts import redirect

    user, _ = User.objects.get_or_create(email=DEMO_EMAIL)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    nxt = request.GET.get("next") or "/cockpit/"
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = "/cockpit/"
    return redirect(nxt)


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
