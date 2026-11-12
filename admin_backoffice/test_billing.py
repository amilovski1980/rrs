from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from admin_backoffice.models import SiteConfiguration
from billing.models import Plan, Subscription, SubscriptionInvoice
from companies.models import Company

User = get_user_model()
PASSWORD = "Cockpit-Lyonnais-2026"


class AdminBillingTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff-factu@rrs.fr", password=PASSWORD, is_staff=True, is_superuser=True)
        self.client_user = User.objects.create_user("client-factu@rrs.fr", password=PASSWORD)
        self.other = User.objects.create_user("autre-factu@rrs.fr")
        self.company = Company.objects.create(
            owner=self.client_user,
            siren="314159265",
            denomination="Atelier Facture",
            forme="SARL",
            regime="reel_simple",
            tva="reel",
            exercice_debut=date(2026, 1, 1),
        )
        self.plan = Plan.objects.create(code="pro", name="Pro", price_eur=Decimal("79.00"))
        self.other_plan = Plan.objects.create(code="micro", name="Micro", price_eur=Decimal("29.00"))
        self.subscription = Subscription.objects.create(
            user=self.client_user,
            plan=self.plan,
            status="past_due",
            stripe_subscription_id="sub_factu_1",
            stripe_customer_id="cus_factu_1",
            follow_up="to_follow",
        )
        Subscription.objects.create(user=self.other, plan=self.other_plan, status="active")
        self.invoice = SubscriptionInvoice.objects.create(
            user=self.client_user,
            subscription=self.subscription,
            external_id="in_factu_1",
            number="ABO-1",
            amount_eur=Decimal("79.00"),
            status="failed",
            description="Abonnement Pro",
            failure_message="Carte refusée",
        )
        SiteConfiguration.objects.create(stripe_secret_key="sk_test_secret_do_not_show")

    def test_client_receives_403(self):
        self.client.login(email="client-factu@rrs.fr", password=PASSWORD)
        urls = [
            reverse("admin_backoffice:billing"),
            reverse("admin_backoffice:billing_invoices"),
            reverse("admin_backoffice:billing_subscriber", kwargs={"pk": self.subscription.pk}),
            reverse("admin_backoffice:billing_invoice", kwargs={"pk": self.invoice.pk}),
            reverse("admin_backoffice:user_billing", kwargs={"pk": self.client_user.pk}),
            reverse("admin_backoffice:company_billing", kwargs={"pk": self.company.pk}),
        ]
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403, url)
            self.assertNotContains(response, "sk_test_secret_do_not_show", status_code=403)

    def test_staff_filters_subscribers_and_opens_the_dossier(self):
        self.client.login(email="staff-factu@rrs.fr", password=PASSWORD)
        listed = self.client.get(reverse("admin_backoffice:billing"), {"status": "past_due", "q": "Facture"})
        self.assertEqual(listed.status_code, 200)
        self.assertContains(listed, "Atelier Facture")
        self.assertContains(listed, "client-factu@rrs.fr")
        self.assertContains(listed, "79")
        self.assertNotContains(listed, "autre-factu@rrs.fr")
        self.assertNotContains(listed, "sk_test_secret_do_not_show")
        detail = self.client.get(reverse("admin_backoffice:billing_subscriber", kwargs={"pk": self.subscription.pk}))
        self.assertContains(detail, "Paiement en échec")
        self.assertContains(detail, "ABO-1")
        self.assertContains(detail, "sub_factu_1")
        company = self.client.get(reverse("admin_backoffice:company_billing", kwargs={"pk": self.company.pk}))
        self.assertContains(company, "Atelier Facture")
        self.assertContains(company, "Carte refusée")
        user_page = self.client.get(reverse("admin_backoffice:user_billing", kwargs={"pk": self.client_user.pk}))
        self.assertContains(user_page, "client-factu@rrs.fr")
        invoices = self.client.get(reverse("admin_backoffice:billing_invoices"), {"status": "failed", "q": "ABO-1"})
        self.assertContains(invoices, "client-factu@rrs.fr")
        self.assertNotContains(invoices, "sk_test")

    def test_staff_note_and_stripe_refresh_do_not_leak_the_secret(self):
        self.client.login(email="staff-factu@rrs.fr", password=PASSWORD)
        noted = self.client.post(
            reverse("admin_backoffice:billing_subscriber", kwargs={"pk": self.subscription.pk}),
            {"action": "note", "follow_up": "reminded", "staff_note": "Relancé par téléphone."},
        )
        self.assertEqual(noted.status_code, 302)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.follow_up, "reminded")
        self.assertIn("téléphone", self.subscription.staff_note)
        with mock.patch(
            "admin_backoffice.billing_admin.retrieve_subscription",
            side_effect=__import__("billing.stripe_api", fromlist=["StripeError"]).StripeError(
                "échec sk_test_secret_do_not_show", status=401,
            ),
        ):
            refreshed = self.client.post(
                reverse("admin_backoffice:billing_subscriber", kwargs={"pk": self.subscription.pk}),
                {"action": "refresh"},
                follow=True,
            )
        self.assertEqual(refreshed.status_code, 200)
        self.assertNotContains(refreshed, "sk_test_secret_do_not_show")
        self.assertContains(refreshed, "masqué")

    def test_staff_sets_a_password_only_with_confirmation_and_can_email_a_reset(self):
        self.client.login(email="staff-factu@rrs.fr", password=PASSWORD)
        page = self.client.get(reverse("admin_backoffice:user_edit", kwargs={"pk": self.other.pk}))
        self.assertContains(page, "Aucun mot de passe utilisable")
        self.assertNotContains(page, "password_hash")
        refused = self.client.post(reverse("admin_backoffice:user_edit", kwargs={"pk": self.other.pk}), {
            "email": self.other.email,
            "phone": "",
            "is_active": "on",
            "password1": PASSWORD,
            "password2": PASSWORD,
        })
        self.assertEqual(refused.status_code, 200)
        self.other.refresh_from_db()
        self.assertFalse(self.other.has_usable_password())
        saved = self.client.post(reverse("admin_backoffice:user_edit", kwargs={"pk": self.other.pk}), {
            "email": self.other.email,
            "phone": "",
            "is_active": "on",
            "password1": PASSWORD,
            "password2": PASSWORD,
            "confirm_password": "on",
        })
        self.assertEqual(saved.status_code, 302)
        self.other.refresh_from_db()
        self.assertTrue(self.other.check_password(PASSWORD))
        self.assertNotIn(PASSWORD, self.other.password)
        again = self.client.get(reverse("admin_backoffice:user_edit", kwargs={"pk": self.other.pk}))
        self.assertNotContains(again, PASSWORD)
        self.assertContains(again, "Un mot de passe est défini")
        unconfirmed = self.client.post(
            reverse("admin_backoffice:user_send_reset", kwargs={"pk": self.other.pk}),
        )
        self.assertEqual(unconfirmed.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)
        sent = self.client.post(
            reverse("admin_backoffice:user_send_reset", kwargs={"pk": self.other.pk}),
            {"confirm": "on"},
        )
        self.assertEqual(sent.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.other.email, mail.outbox[0].to)
        self.assertNotIn(PASSWORD, mail.outbox[0].body)
        self.assertNotIn("sk_", mail.outbox[0].body)
