from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from companies.models import Company

from .models import Supplier


class SupplierLookupTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(email="fournisseur@example.fr")
        self.company = Company.objects.create(
            owner=user,
            siren="777888999",
            denomination="Atelier Fournisseur",
            regime="reel_simple",
            tva="reel",
        )
        self.client.force_login(user)

    def test_lookup_results_prefill_the_supplier_form(self):
        rows = [
            {
                "siren": "812345678",
                "siret": "81234567800012",
                "denomination": "Menuiserie Dupont",
                "adresse": "12 rue des Ateliers, 69003 Lyon",
                "naf": "43.32A",
                "forme": "SARL",
                "etat": "Active",
                "tva": "FR28812345678",
                "notes": "SIREN 812345678 · NAF 43.32A · SARL",
            }
        ]
        with patch("suppliers.views.search_entreprises", return_value=(rows, None)):
            response = self.client.get(
                reverse("suppliers:lookup") + f"?societe={self.company.id}&q=Dupont"
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Menuiserie Dupont")
        self.assertContains(response, "Utiliser cette société")

    def test_create_form_accepts_lookup_prefill(self):
        response = self.client.get(
            reverse("suppliers:create")
            + f"?societe={self.company.id}"
            + "&name=Menuiserie%20Dupont&siret=81234567800012"
            + "&tva=FR28812345678&address=12%20rue%20des%20Ateliers"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Menuiserie Dupont")
        self.assertContains(response, "81234567800012")
        self.assertContains(response, "FR28812345678")

    def test_supplier_list_search_accepts_a_siren(self):
        Supplier.objects.create(
            company=self.company,
            name="Menuiserie Dupont",
            siret="81234567800012",
        )
        response = self.client.get(
            reverse("suppliers:list") + f"?societe={self.company.id}&q=812345678"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Menuiserie Dupont")
