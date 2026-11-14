from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from companies.models import Company


CARD = {
    "siren": "123456789",
    "siret": "12345678900011",
    "denomination": "ATELIER MARTIN",
    "forme": "SARL",
    "categorie_juridique": "5499",
    "adresse": "12 RUE DES ARTISANS 75011 PARIS",
    "code_naf": "4332A",
    "naf": "43.32A",
    "activite_suggeree": "btp",
    "date_creation": "2020-01-01",
    "etat": "Active",
    "tranche_effectifs": "00",
}


class OnboardingSearchTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("dirigeant@exemple.fr")
        self.client.force_login(self.user)

    def test_page_accepts_a_company_name_or_a_siren(self):
        response = self.client.get("/ajouter/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nom de la société ou SIREN")
        self.assertContains(response, 'id="id_siren"')
        self.assertContains(response, "Nom de la société ou 123 456 789")

    def test_name_search_lists_matches_with_a_selection_link(self):
        with patch("companies.views.search_entreprises", return_value=([CARD], None)) as search:
            response = self.client.post("/ajouter/", {"siren": "atelier martin"})
        self.assertEqual(response.status_code, 200)
        search.assert_called_once_with("atelier martin")
        self.assertContains(response, "ATELIER MARTIN")
        self.assertContains(response, "SIREN 123456789")
        self.assertContains(response, "/inscription/choisir/?siren=123456789")
        self.assertContains(response, "12 RUE DES ARTISANS")

    def test_unknown_name_shows_a_friendly_message(self):
        with patch("companies.views.search_entreprises", return_value=([], None)):
            response = self.client.post("/ajouter/", {"siren": "societe inconnue"})
        self.assertContains(response, "Aucune société ne correspond")

    def test_name_search_rate_limit_is_explained(self):
        with patch("companies.views.search_entreprises", return_value=([], "rate_limit")):
            response = self.client.post("/ajouter/", {"siren": "menuiserie"})
        self.assertContains(response, "très sollicité")

    def test_short_query_is_rejected_before_any_lookup(self):
        with patch("companies.views.search_entreprises") as search:
            response = self.client.post("/ajouter/", {"siren": "a"})
        self.assertContains(response, "2 caractères minimum")
        search.assert_not_called()

    def test_formatted_siren_still_uses_the_official_lookup(self):
        with patch("companies.views.lookup_siren", return_value=(dict(CARD), None)) as lookup:
            response = self.client.post("/ajouter/", {"siren": "123 456 789"})
        self.assertRedirects(response, "/ajouter/confirmer/", fetch_redirect_response=False)
        lookup.assert_called_once_with("123456789")
        self.assertEqual(self.client.session["onboarding_lookup"]["siren"], "123456789")
        self.assertNotIn("raw", self.client.session["onboarding_lookup"]["data"])

    def test_siret_uses_its_nine_digit_siren(self):
        with patch("companies.views.lookup_siren", return_value=(dict(CARD), None)) as lookup:
            response = self.client.post("/ajouter/", {"siren": "12345678900011"})
        self.assertRedirects(response, "/ajouter/confirmer/", fetch_redirect_response=False)
        lookup.assert_called_once_with("123456789")

    def test_company_already_in_the_cockpit_is_not_looked_up(self):
        Company.objects.create(
            owner=self.user,
            siren="123456789",
            denomination="Atelier Martin",
            forme="SARL",
            regime="reel_simple",
            tva="reel",
            exercice_debut="2026-01-01",
        )
        with patch("companies.views.lookup_siren") as lookup:
            response = self.client.post("/ajouter/", {"siren": "123456789"})
        self.assertContains(response, "déjà dans votre cockpit")
        lookup.assert_not_called()

    def test_choosing_a_search_result_opens_the_onboarding_confirmation(self):
        with patch("companies.signup.official_card", return_value=(dict(CARD), None)):
            response = self.client.get("/inscription/choisir/", {"siren": "123456789"})
        self.assertRedirects(response, "/ajouter/confirmer/", fetch_redirect_response=False)
        self.assertEqual(self.client.session["onboarding_lookup"]["siren"], "123456789")
        page = self.client.get("/ajouter/confirmer/")
        self.assertContains(page, "ATELIER MARTIN")
