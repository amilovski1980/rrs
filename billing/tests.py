import hashlib
import hmac
import json
import time
from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import OperationalError
from django.test import TestCase, override_settings
from django.urls import reverse

from accounting.services import generate_portal
from admin_backoffice.models import SiteConfiguration
from companies.models import Company
from documents.models import Invoice, InvoiceLine
from documents.pdf import render_invoice_pdf

from .access import company_create_block, feature_on, invoice_create_block
from .models import Plan, Subscription
from .services import record_and_apply


def _user(email):
    return get_user_model().objects.create_user(email)


def _company(owner, siren="512345678"):
    company = Company.objects.create(
        owner=owner,
        siren=siren,
        denomination="Atelier Martin",
        forme="SARL",
        regime="reel_simple",
        tva="reel",
        address="12 rue des Artisans, 69001 Lyon",
        exercice_debut=date(2026, 1, 1),
    )
    generate_portal(company)
    return company


def _sign(secret, body: bytes, stamp=None):
    stamp = int(time.time()) if stamp is None else stamp
    digest = hmac.new(secret.encode(), f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()
    return stamp, f"t={stamp},v1={digest}"


class PlanGatingTests(TestCase):
    def setUp(self):
        self.user = _user("artisan@exemple.fr")
        self.company = _company(self.user)
        self.micro = Plan.objects.create(
            code="micro", name="Micro", price_eur=Decimal("29.00"), max_companies=1, max_invoices_month=1,
        )
        self.pro = Plan.objects.create(code="pro", name="Pro", price_eur=Decimal("79.00"))
        self.subscription = Subscription.objects.create(user=self.user, plan=self.micro, status="active")
        self.client.force_login(self.user)

    def test_locked_feature_stays_visible_and_invites_upgrade(self):
        cockpit = self.client.get("/cockpit/")
        self.assertEqual(cockpit.status_code, 200)
        self.assertContains(cockpit, "Devis")
        self.assertContains(cockpit, "Mettre à jour le forfait")
        locked = self.client.get("/factures/devis/")
        self.assertEqual(locked.status_code, 302)
        self.assertIn("/forfait/", locked["Location"])
        followed = self.client.get("/factures/devis/", follow=True)
        self.assertContains(followed, "Mettre à jour le forfait")
        self.assertFalse(feature_on(self.user, "quotes"))
        self.assertTrue(feature_on(self.user, "invoices"))

    def test_pro_plan_opens_the_same_page(self):
        self.subscription.plan = self.pro
        self.subscription.save(update_fields=["plan"])
        page = self.client.get("/factures/devis/")
        self.assertEqual(page.status_code, 200)
        self.assertTrue(feature_on(self.user, "quotes"))
        self.assertTrue(feature_on(self.user, "ai_voice"))

    def test_account_without_plan_keeps_historical_access(self):
        self.subscription.delete()
        page = self.client.get("/factures/devis/")
        self.assertEqual(page.status_code, 200)
        self.assertTrue(feature_on(self.user, "quotes"))

    def test_invoice_cap_blocks_creation_without_error(self):
        Invoice.objects.create(
            company=self.company, number="BR-deja", client_name="Client", amount_ht=Decimal("10.00"),
        )
        self.assertIsNotNone(invoice_create_block(self.user))
        response = self.client.post("/factures/nouvelle/", {
            "client": "",
            "project": "",
            "client_name": "Nouveau",
            "client_siren": "",
            "amount_ht": "40.00",
            "vat_rate": "20.00",
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn("/forfait/", response["Location"])
        self.assertEqual(Invoice.objects.filter(company=self.company).count(), 1)

    def test_company_cap(self):
        self.assertIsNotNone(company_create_block(self.user))

    def test_locked_theme_is_refused(self):
        response = self.client.post("/societe/", {"theme": "indigo"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/forfait/", response["Location"])
        self.company.refresh_from_db()
        self.assertEqual(self.company.invoice_theme, "azur")


class StripeFlowTests(TestCase):
    def setUp(self):
        self.user = _user("payer@exemple.fr")
        self.company = _company(self.user, siren="512345679")
        self.micro = Plan.objects.create(code="micro", name="Micro", price_eur=Decimal("29.00"))
        self.pro = Plan.objects.create(code="pro", name="Pro", price_eur=Decimal("79.00"), trial_days=14)
        Subscription.objects.create(user=self.user, plan=self.micro, status="active")
        self.client.force_login(self.user)

    def test_missing_stripe_config_is_a_message(self):
        with mock.patch("billing.views.stripe_secret", return_value=""):
            response = self.client.post(reverse("plan_checkout"), {"plan": "pro"}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "n'est pas configuré")
        self.assertNotContains(response, "sk_")

    def test_checkout_redirects_to_stripe(self):
        with mock.patch("billing.views.stripe_secret", return_value="sk_test_secret_value"):
            with mock.patch(
                "billing.views.create_checkout_session",
                return_value={"url": "https://checkout.stripe.com/c/pay/cs_test_session"},
            ) as created:
                response = self.client.post(reverse("plan_checkout"), {"plan": "pro"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("checkout.stripe.com", response["Location"])
        self.assertNotIn("sk_test_secret_value", response["Location"])
        self.assertEqual(created.call_args.kwargs["plan"].code, "pro")

    def _event(self, event_id, kind, obj):
        return {"id": event_id, "type": kind, "data": {"object": obj}}

    def _post(self, event, secret="whsec_test"):
        body = json.dumps(event).encode()
        _stamp, header = _sign(secret, body)
        with override_settings(STRIPE_WEBHOOK_SECRET=secret):
            return self.client.post(
                reverse("stripe_webhook"),
                data=body,
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE=header,
            )

    def test_webhook_updates_plan_and_is_idempotent(self):
        event = self._event("evt_checkout_1", "checkout.session.completed", {
            "mode": "subscription",
            "client_reference_id": str(self.user.pk),
            "payment_status": "paid",
            "subscription": "sub_pro_123",
            "customer": "cus_123",
            "metadata": {"user_id": str(self.user.pk), "plan_code": "pro"},
        })
        first = self._post(event)
        self.assertEqual(first.status_code, 200)
        self.user.subscriptions.get().refresh_from_db()
        sub = self.user.subscriptions.get()
        self.assertEqual(sub.plan.code, "pro")
        self.assertEqual(sub.status, "active")
        self.assertEqual(sub.stripe_subscription_id, "sub_pro_123")
        again = self._post(event)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(self.user.subscriptions.count(), 1)
        self.assertTrue(feature_on(self.user, "ai_voice"))
        page = self.client.get("/factures/devis/")
        self.assertEqual(page.status_code, 200)

    def test_subscription_updated_canceled_and_payment_failed(self):
        record_and_apply(self._event("evt_up", "customer.subscription.updated", {
            "id": "sub_pro_123",
            "status": "active",
            "customer": "cus_123",
            "current_period_end": 1_800_000_000,
            "metadata": {"user_id": str(self.user.pk), "plan_code": "pro"},
        }))
        sub = self.user.subscriptions.get()
        self.assertEqual(sub.plan.code, "pro")
        self.assertIsNotNone(sub.current_period_end)
        failed = self._post(self._event("evt_fail", "invoice.payment_failed", {"subscription": "sub_pro_123"}))
        self.assertEqual(failed.status_code, 200)
        sub.refresh_from_db()
        self.assertEqual(sub.status, "past_due")
        canceled = self._post(self._event("evt_del", "customer.subscription.deleted", {
            "id": "sub_pro_123",
            "status": "canceled",
            "metadata": {"user_id": str(self.user.pk), "plan_code": "pro"},
        }))
        self.assertEqual(canceled.status_code, 200)
        sub.refresh_from_db()
        self.assertEqual(sub.status, "canceled")
        self.assertFalse(feature_on(self.user, "ai_voice"))

    def test_bad_signature_and_missing_secret(self):
        body = b'{"id":"evt_x","type":"checkout.session.completed","data":{"object":{}}}'
        with override_settings(STRIPE_WEBHOOK_SECRET="whsec_test"):
            bad = self.client.post(
                reverse("stripe_webhook"),
                data=body,
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="t=1,v1=dead",
            )
        self.assertEqual(bad.status_code, 400)
        self.assertNotIn(b"whsec_test", bad.content)
        with override_settings(STRIPE_WEBHOOK_SECRET=""):
            missing = self.client.post(reverse("stripe_webhook"), data=body, content_type="application/json")
        self.assertEqual(missing.status_code, 400)
        self.assertIn("non configuré", missing.content.decode())


class AiProviderTests(TestCase):
    def setUp(self):
        self.user = _user("ia@exemple.fr")
        self.company = _company(self.user, siren="512345670")

    def test_backoffice_choice_points_chat_at_xai(self):
        SiteConfiguration.objects.create(
            ai_text_provider="xai",
            xai_api_key="xai-secret-do-not-leak",
            xai_text_model="grok-3",
        )
        from ai.chat import get_or_create_conversation, run_chat_turn
        from ai.providers import text_provider

        spec = text_provider()
        self.assertEqual(spec["code"], "xai")
        self.assertEqual(spec["base"], "https://api.x.ai/v1")
        self.assertEqual(spec["model"], "grok-3")
        conversation = get_or_create_conversation(self.user, self.company)
        with mock.patch("ai.chat.QwenClient") as client_cls:
            client_cls.return_value.chat.return_value = {
                "choices": [{"message": {"content": "Bonjour.", "tool_calls": []}}],
            }
            result = run_chat_turn(self.user, self.company, conversation, "Bonjour")
        self.assertTrue(result["ok"])
        self.assertFalse(result["fallback"])
        self.assertNotIn("xai-secret-do-not-leak", result["reply"])
        kwargs = client_cls.call_args.kwargs
        self.assertEqual(kwargs["base"], "https://api.x.ai/v1")
        self.assertEqual(kwargs["model"], "grok-3")
        self.assertEqual(kwargs["api_key"], "xai-secret-do-not-leak")

    @override_settings(XAI_API_KEY="", LLM_BASE_URL="")
    def test_unconfigured_provider_is_graceful(self):
        SiteConfiguration.objects.create(ai_text_provider="xai", xai_api_key="")
        from ai.chat import get_or_create_conversation, run_chat_turn

        conversation = get_or_create_conversation(self.user, self.company)
        result = run_chat_turn(self.user, self.company, conversation, "Bonjour")
        self.assertTrue(result["ok"])
        self.assertTrue(result["fallback"])
        self.assertIn("pas disponible", result["reply"])


class InvoicePdfAndPagesTests(TestCase):
    def setUp(self):
        self.user = _user("pdf@exemple.fr")
        self.company = _company(self.user, siren="512345671")
        self.invoice = Invoice.objects.create(
            company=self.company,
            number="BR-pdf",
            client_name="Client Démo",
            client_siren="552100554",
            amount_ht=Decimal("100.00"),
            vat_rate=Decimal("20.00"),
        )
        InvoiceLine.objects.create(
            invoice=self.invoice,
            description="Pose de fenêtre bois sur mesure, chantier Lyon centre, avec finitions.",
            quantity=Decimal("2"),
            unit_price=Decimal("50.00"),
            vat_rate=Decimal("20.00"),
        )
        self.client.force_login(self.user)

    def test_pdf_is_a_non_empty_document(self):
        payload = render_invoice_pdf(self.invoice, self.company)
        self.assertTrue(payload.startswith(b"%PDF"))
        self.assertGreater(len(payload), 800)
        for code, _label in (
            ("azur", "Azur"),
            ("carmin", "Carmin"),
            ("encre", "Encre"),
            ("sauge", "Sauge"),
            ("graphite", "Graphite"),
            ("indigo", "Indigo"),
            ("terra", "Terra"),
        ):
            self.company.invoice_theme = code
            themed = render_invoice_pdf(self.invoice, self.company)
            self.assertTrue(themed.startswith(b"%PDF"), code)
            self.assertGreater(len(themed), 800, code)

    def test_key_pages_return_200(self):
        self.assertEqual(self.client.get("/cockpit/").status_code, 200)
        upgrade = self.client.get(reverse("plan_upgrade"))
        self.assertEqual(upgrade.status_code, 200)
        self.assertContains(upgrade, "Mettre à jour le forfait")
        detail = self.client.get(f"/factures/{self.invoice.id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Client Démo")
        self.assertContains(detail, "SIREN")
        staff = _user("staff-pages@exemple.fr")
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])
        self.client.force_login(staff)
        integrations = self.client.get(reverse("admin_backoffice:integrations"))
        self.assertEqual(integrations.status_code, 200)
        self.assertContains(integrations, "xAI / Grok")
        self.assertContains(integrations, "Stripe")
        settings_page = self.client.get(reverse("admin_backoffice:settings"))
        self.assertEqual(settings_page.status_code, 200)
        self.assertContains(settings_page, "Fournisseur du chat Aminia")
        self.assertNotContains(settings_page, "xai-secret")


def _pricing_section(response) -> str:
    body = response.content.decode()
    start = body.index('id="pricing"')
    end = body.index('id="securite"')
    return body[start:end]


class HomepagePricingTests(TestCase):
    """La vitrine publique affiche les forfaits, sans ouvrir un autre parcours d'inscription."""

    def test_fallback_shows_default_matrix_without_writing(self):
        self.assertEqual(Plan.objects.count(), 0)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Plan.objects.count(), 0)
        section = _pricing_section(response)
        self.assertIn("29 €", section)
        self.assertIn("49 €", section)
        self.assertIn("79 €", section)
        self.assertIn("HT / mois", section)
        self.assertIn("1 société", section)
        self.assertIn("20 factures / mois", section)
        self.assertIn("40 messages Aminia / mois", section)
        self.assertIn("Modèles Azur et Carmin", section)
        self.assertIn("Écritures, grand livre et balance", section)
        self.assertIn("Factures, clients et PDF", section)
        self.assertIn("3 sociétés", section)
        self.assertIn("80 factures / mois", section)
        self.assertIn("200 messages Aminia / mois", section)
        self.assertIn("Modèles Azur, Carmin, Encre et Sauge", section)
        self.assertIn("Devis, catalogue et projets", section)
        self.assertIn("Avoirs, paiements et import PDF", section)
        self.assertIn("Brouillons IA", section)
        self.assertIn("Sociétés illimitées", section)
        self.assertIn("Factures illimitées", section)
        self.assertIn("Messages Aminia illimités", section)
        self.assertIn("Les 7 modèles de facture", section)
        self.assertIn("Tickets de caisse", section)
        self.assertIn("Voix Aminia", section)
        self.assertIn("Tarifs mensuels hors taxes", section)
        self.assertIn("Le montant débité correspond au prix affiché.", section)
        self.assertNotIn("TTC", section)
        self.assertNotIn("20 %", section)
        self.assertIn('class="plan hot" data-plan="reel"', section)
        self.assertIn("Le plus choisi", section)
        self.assertIn("Sans carte bancaire · essai 14 jours", response.content.decode())

    def test_calls_to_action_reuse_company_search(self):
        response = self.client.get("/")
        self.assertContains(response, 'id="recherche"')
        self.assertContains(response, 'name="q"')
        self.assertContains(response, 'action="/recherche/"')
        self.assertContains(response, "SIRET")
        section = _pricing_section(response)
        self.assertEqual(section.count('href="#recherche"'), 3)
        self.assertContains(
            response,
            '<a class="btn btn-lg btn-primary" href="#recherche">Commencer l\'essai</a>',
            html=True,
        )
        self.assertNotIn("/inscription/", section)
        self.assertNotIn("/forfait/", section)
        self.assertNotIn("plan_checkout", section)
        self.assertIn("btn-lg btn-primary", section)
        self.assertIn("btn-lg btn-ghost", section)

    def test_published_plans_replace_the_fallback(self):
        Plan.objects.create(
            code="micro",
            name="Micro secret",
            price_eur=Decimal("29.00"),
            is_active=False,
            description="Ne doit pas s'afficher.",
        )
        Plan.objects.create(
            code="atelier",
            name="Atelier",
            price_eur=Decimal("19.50"),
            is_active=True,
            description="Pour un seul atelier.",
            max_companies=2,
            max_invoices_month=1,
            max_ai_requests_month=None,
            trial_days=7,
            entitlements={
                "custom": True,
                "entries": True,
                "ledger": False,
                "balance": False,
                "invoices": True,
                "clients": True,
                "invoice_pdf": False,
                "themes": ["sauge"],
            },
        )
        Plan.objects.create(
            code="pro",
            name="Pro",
            price_eur=Decimal("90.00"),
            is_active=True,
            description="Le grand atelier.",
            max_companies=None,
            max_invoices_month=None,
            max_ai_requests_month=3,
            trial_days=7,
            entitlements={
                "custom": True,
                "entries": True,
                "ledger": True,
                "balance": True,
                "tickets": False,
                "ai_voice": False,
                "themes": ["azur", "carmin"],
            },
        )
        response = self.client.get("/")
        section = _pricing_section(response)
        self.assertLess(section.index('data-plan="atelier"'), section.index('data-plan="pro"'))
        self.assertIn("19,50 €", section)
        self.assertIn("90 €", section)
        self.assertIn("2 sociétés", section)
        self.assertIn("1 facture / mois", section)
        self.assertIn("Messages Aminia illimités", section)
        self.assertIn("Modèle Sauge", section)
        self.assertIn("Pour un seul atelier.", section)
        self.assertIn("3 messages Aminia / mois", section)
        self.assertIn("Essai 7 jours", section)
        self.assertNotIn("Micro secret", section)
        self.assertNotIn("29 €", section)
        self.assertNotIn("49 €", section)
        self.assertNotIn("Tickets de caisse", section)
        self.assertNotIn("Voix Aminia", section)
        self.assertNotIn("Le plus choisi", section)
        self.assertIn("Sans carte bancaire · essai 7 jours", response.content.decode())

    def test_entitlement_edit_changes_the_reel_card(self):
        from billing.catalog import matrix_for_tier

        matrix = matrix_for_tier("standard")
        matrix["products"] = False
        matrix["projects"] = False
        matrix["themes"] = ["azur", "encre"]
        Plan.objects.create(
            code="reel",
            name="Réel",
            price_eur=Decimal("59.00"),
            is_active=True,
            max_companies=5,
            max_invoices_month=12,
            max_ai_requests_month=8,
            description="Réel ajusté.",
            entitlements=matrix,
        )
        response = self.client.get("/")
        section = _pricing_section(response)
        self.assertIn("59 €", section)
        self.assertIn("5 sociétés", section)
        self.assertIn("12 factures / mois", section)
        self.assertIn("8 messages Aminia / mois", section)
        self.assertIn("Modèles Azur et Encre", section)
        self.assertIn("Devis", section)
        self.assertNotIn("catalogue", section)
        self.assertNotIn("projets", section)
        self.assertIn('class="plan hot" data-plan="reel"', section)
        self.assertIn('href="#recherche"', section)

    def test_unpublished_plans_are_not_replaced_by_the_catalog(self):
        Plan.objects.create(
            code="micro",
            name="Micro secret",
            price_eur=Decimal("29.00"),
            is_active=False,
        )
        response = self.client.get("/")
        section = _pricing_section(response)
        self.assertIn("dès qu'ils seront publiés", section)
        self.assertNotIn("Micro secret", section)
        self.assertNotIn("49 €", section)
        self.assertNotIn('href="#recherche"', section)
        self.assertContains(response, 'id="recherche"')
        self.assertContains(response, 'action="/recherche/"')

    def test_database_error_falls_back_to_the_catalog(self):
        with mock.patch(
            "billing.models.Plan.objects.order_by",
            side_effect=OperationalError("billing_plan absente"),
        ):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        section = _pricing_section(response)
        self.assertIn("Micro", section)
        self.assertIn("29 €", section)
        self.assertIn("Réel", section)
        self.assertIn("Pro", section)
        self.assertIn('href="#recherche"', section)
