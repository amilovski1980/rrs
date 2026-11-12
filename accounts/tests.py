from django.contrib.auth import get_user_model
from django.test import TestCase

from core.demo import DEMO_EMAIL


class EmailLoginTests(TestCase):
    def test_unknown_email_does_not_open_an_empty_cockpit(self):
        response = self.client.post("/compte/", {"email": "artisan@exemple.fr"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aucun compte ne correspond")
        self.assertContains(response, "Essayer la démo")
        self.assertFalse(get_user_model().objects.filter(email="artisan@exemple.fr").exists())

    def test_same_email_reopens_the_same_account(self):
        get_user_model().objects.create_user("artisan@exemple.fr")
        self.client.post("/compte/", {"email": "artisan@exemple.fr"})
        cockpit = self.client.get("/cockpit/")
        self.assertContains(cockpit, "artisan@exemple.fr")
        self.client.post("/compte/logout/")
        again = self.client.post("/compte/", {"email": "Artisan@exemple.fr"})
        self.assertRedirects(again, "/cockpit/", fetch_redirect_response=False)
        self.assertEqual(get_user_model().objects.filter(email__iexact="artisan@exemple.fr").count(), 1)

    def test_demo_email_opens_the_seeded_company(self):
        response = self.client.post("/compte/", {"email": DEMO_EMAIL}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Menuiserie Dupont")

    def test_demo_login_with_existing_devis_avoir_series(self):
        """seed_demo must target FAC explicitly when DEV/AVO series already exist."""
        from core.demo import seed_demo
        from documents.models import InvoiceSeries

        user, company = seed_demo()
        InvoiceSeries.objects.get_or_create(
            company=company, year=2026, prefix="DEV", defaults={"last_number": 1}
        )
        InvoiceSeries.objects.get_or_create(
            company=company, year=2026, prefix="AVO", defaults={"last_number": 1}
        )
        # Second seed (and /compte/ demo email) used to raise MultipleObjectsReturned.
        seed_demo()
        response = self.client.post("/compte/", {"email": DEMO_EMAIL}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Menuiserie Dupont")
        self.assertEqual(
            InvoiceSeries.objects.filter(company=company, year=2026).count(), 3
        )
