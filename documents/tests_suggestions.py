from django.contrib.auth import get_user_model
from django.test import TestCase

from companies.models import Company

from .models import Product
from .suggestions import product_suggestions


class ProductSuggestionTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(email="suggestions@example.fr")
        self.company = Company.objects.create(
            owner=user,
            siren="812345679",
            denomination="Transports Martin",
            regime="reel_simple",
            tva="reel",
            activites=["transport"],
        )

    def test_transport_company_gets_transport_suggestions(self):
        labels = [item["label"] for item in product_suggestions(self.company)]
        self.assertIn("Transport de marchandises", labels)
        self.assertIn("Transport de matériel", labels)
        self.assertIn("Livraison sur chantier", labels)

    def test_generic_suggestions_are_always_available(self):
        self.company.activites = []
        self.company.denomination = "Atelier Test"
        self.company.save(update_fields=["activites", "denomination"])
        labels = [item["label"] for item in product_suggestions(self.company)]
        self.assertIn("Main d'œuvre", labels)
        self.assertIn("Fourniture", labels)

    def test_existing_products_are_suggested_without_duplicates(self):
        Product.objects.create(
            company=self.company,
            label="Transport de marchandises",
            description="Déjà au catalogue",
        )
        Product.objects.create(
            company=self.company,
            label="Palette Europe",
            description="Livraison palette",
        )
        items = product_suggestions(self.company)
        labels = [item["label"] for item in items]
        self.assertEqual(labels.count("Transport de marchandises"), 1)
        self.assertIn("Palette Europe", labels)
