from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from companies.models import Company
from documents.models import Client as Customer
from documents.models import Invoice, Product

from .demo import (
    DEMO_SANDBOX_DOMAIN,
    DEMO_SANDBOX_PREFIX,
    _cleanup_sandboxes,
)


class DemoSandboxTests(TestCase):
    def test_demo_login_creates_a_real_isolated_workspace(self):
        response = self.client.get(reverse("demo_login"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/cockpit/", response["Location"])

        user = get_user_model().objects.get(
            email__istartswith=DEMO_SANDBOX_PREFIX,
            email__iendswith=DEMO_SANDBOX_DOMAIN,
        )
        company = Company.objects.get(owner=user)
        self.assertTrue(company.denomination)
        self.assertNotEqual(company.siren, "812345678")
        self.assertGreaterEqual(company.invoices.count(), 2)
        self.assertGreaterEqual(Customer.objects.filter(company=company).count(), 2)
        self.assertGreaterEqual(Product.objects.filter(company=company).count(), 2)
        self.assertTrue(
            Invoice.objects.filter(company=company, number="FAC-2026-00043").exists()
        )

    def test_same_session_reuses_its_sandbox(self):
        self.client.get(reverse("demo_login"))
        first = Company.objects.get(owner__email__istartswith=DEMO_SANDBOX_PREFIX)
        self.client.get(reverse("demo_login"))
        companies = Company.objects.filter(
            owner__email__istartswith=DEMO_SANDBOX_PREFIX
        )
        self.assertEqual(companies.count(), 1)
        self.assertEqual(companies.first().pk, first.pk)

    def test_two_visitors_get_two_separate_sandboxes(self):
        first_client = Client()
        first_client.get(reverse("demo_login"))
        second_client = Client()
        second_client.get(reverse("demo_login"))
        companies = Company.objects.filter(
            owner__email__istartswith=DEMO_SANDBOX_PREFIX
        )
        self.assertEqual(companies.count(), 2)
        self.assertEqual(
            companies.values_list("siren", flat=True).distinct().count(), 2
        )

    def test_stale_sandboxes_are_removed(self):
        self.client.get(reverse("demo_login"))
        user = get_user_model().objects.get(
            email__istartswith=DEMO_SANDBOX_PREFIX
        )
        get_user_model().objects.filter(pk=user.pk).update(
            created_at=timezone.now() - timedelta(days=2)
        )
        _cleanup_sandboxes()
        self.assertFalse(get_user_model().objects.filter(pk=user.pk).exists())
