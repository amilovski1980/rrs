from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from companies.models import Company
from documents.models import Invoice

from .demo import (
    DEMO_EMAIL,
    DEMO_SANDBOX_DOMAIN,
    DEMO_SANDBOX_PREFIX,
    DEMO_SIREN,
    purge_demo_sandboxes,
)


class DemoReadOnlyTests(TestCase):
    def test_demo_login_uses_one_shared_workspace(self):
        response = self.client.get(reverse("demo_login"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/cockpit/", response["Location"])

        user = get_user_model().objects.get(email=DEMO_EMAIL)
        company = Company.objects.get(owner=user, siren=DEMO_SIREN)
        self.assertTrue(company.invoices.exists())
        self.assertTrue(company.purchase_invoices.exists())
        self.assertTrue(company.bank_accounts.exists())
        self.assertFalse(
            get_user_model()
            .objects.filter(
                email__istartswith=DEMO_SANDBOX_PREFIX,
                email__iendswith=DEMO_SANDBOX_DOMAIN,
            )
            .exists()
        )

    def test_two_visitors_share_the_fixed_demo(self):
        first = Client()
        second = Client()
        first.get(reverse("demo_login"))
        second.get(reverse("demo_login"))

        self.assertEqual(Company.objects.filter(siren=DEMO_SIREN).count(), 1)
        self.assertFalse(
            get_user_model()
            .objects.filter(email__istartswith=DEMO_SANDBOX_PREFIX)
            .exists()
        )

    def test_demo_writes_are_blocked(self):
        self.client.get(reverse("demo_login"))
        before = Invoice.objects.count()
        response = self.client.post(
            reverse("invoice_create"),
            {"client_name": "Tentative démo", "lines-TOTAL_FORMS": "0"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Invoice.objects.count(), before)
        self.assertFalse(Invoice.objects.filter(client_name="Tentative démo").exists())

    def test_demo_banner_is_visible(self):
        self.client.get(reverse("demo_login"))
        response = self.client.get(reverse("cockpit"), follow=True)
        self.assertContains(response, "Mode démo")
        self.assertContains(response, "lecture seule")

    def test_purge_removes_legacy_sandboxes(self):
        sandbox = get_user_model().objects.create_user(
            email=f"{DEMO_SANDBOX_PREFIX}legacy{DEMO_SANDBOX_DOMAIN}"
        )
        company = Company.objects.create(
            owner=sandbox,
            siren="999888777",
            denomination="Ancien bac à sable",
            regime="reel_simple",
        )
        removed = purge_demo_sandboxes()
        self.assertGreaterEqual(removed, 1)
        self.assertFalse(get_user_model().objects.filter(pk=sandbox.pk).exists())
        self.assertFalse(Company.objects.filter(pk=company.pk).exists())
