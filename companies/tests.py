from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Company


class CompanySettingsTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("atelier@exemple.fr")
        self.company = Company.objects.create(
            owner=user,
            siren="812345679",
            denomination="Atelier Test",
            forme="SARL",
            regime="reel_simple",
            tva="reel",
            exercice_debut=date(2026, 1, 1),
            address="1 rue du Bois 75011 Paris",
        )
        self.client.force_login(user)

    def test_settings_save_phone_and_theme(self):
        page = self.client.get("/societe/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "1 rue du Bois")
        saved = self.client.post("/societe/", {
            "denomination": "Atelier Test",
            "forme": "SARL",
            "address": "12 rue des Artisans 75011 Paris",
            "phone": "06 12 34 56 78",
            "email": "compta@atelier.fr",
            "invoice_theme": "carmin",
        })
        self.assertEqual(saved.status_code, 302)
        self.company.refresh_from_db()
        self.assertEqual(self.company.phone, "06 12 34 56 78")
        self.assertEqual(self.company.invoice_theme, "carmin")
        self.assertIn("Artisans", self.company.address)

    def test_theme_switch_from_invoice_page(self):
        response = self.client.post("/societe/", {
            "theme": "encre",
            "next": "/cockpit/",
        })
        self.assertRedirects(response, "/cockpit/", fetch_redirect_response=False)
        self.company.refresh_from_db()
        self.assertEqual(self.company.invoice_theme, "encre")


    def test_new_invoice_themes_listed(self):
        page = self.client.get("/societe/")
        self.assertEqual(page.status_code, 200)
        for label in ("Graphite", "Indigo", "Terra"):
            self.assertContains(page, label)

    def test_accepts_graphite_theme(self):
        response = self.client.post("/societe/", {
            "theme": "graphite",
            "next": "/cockpit/",
        })
        self.assertEqual(response.status_code, 302)
        self.company.refresh_from_db()
        self.assertEqual(self.company.invoice_theme, "graphite")



class LandingPageTests(TestCase):
    def test_home_renders_without_utility_bar(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'class="utility"')
        self.assertNotContains(response, "utility-in")
        self.assertContains(response, 'class="nav"')
