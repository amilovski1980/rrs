from unittest.mock import Mock, patch

import httpx
from django.core.cache import cache
from django.test import TestCase

from integrations.insee import (
    official_card,
    parse_company_query,
    search_entreprises,
    slim_annuaire_hit,
)


API_HIT = {
    "siren": "123456789",
    "nom_complet": "ATELIER MARTIN",
    "nom_raison_sociale": "ATELIER MARTIN",
    "nature_juridique": "5499",
    "activite_principale": "43.32A",
    "etat_administratif": "A",
    "date_creation": "2018-04-01",
    "tranche_effectif_salarie": "03",
    "dirigeants": [{"nom": "SECRET"}],
    "finances": {"ca": 999},
    "siege": {
        "siret": "12345678900012",
        "adresse": "12 RUE DES ARTISANS 75011 PARIS",
        "geo_adresse": None,
        "activite_principale": "43.32A",
    },
    "matching_etablissements": [],
}


def _response(status, payload=None):
    response = Mock()
    response.status_code = status
    response.json.return_value = payload if payload is not None else {}
    return response


class ParseCompanyQueryTests(TestCase):
    def test_name_siren_and_siret(self):
        self.assertEqual(parse_company_query("  Menuiserie Dupont "), ("name", "Menuiserie Dupont"))
        self.assertEqual(parse_company_query("123 456 789"), ("siren", "123456789"))
        self.assertEqual(parse_company_query("123 456 789 00012"), ("siret", "12345678900012"))

    def test_rejects_incomplete_digits_and_tiny_names(self):
        self.assertEqual(parse_company_query("12345")[0], "invalid")
        self.assertEqual(parse_company_query("a")[0], "invalid")
        self.assertEqual(parse_company_query("   ")[0], "invalid")


class SearchEntreprisesTests(TestCase):
    def setUp(self):
        cache.clear()

    @patch("integrations.insee.httpx.get")
    def test_name_search_returns_a_slim_card(self, get):
        get.return_value = _response(200, {"results": [API_HIT]})
        results, error = search_entreprises("atelier martin")
        self.assertIsNone(error)
        self.assertEqual(len(results), 1)
        card = results[0]
        self.assertEqual(card["siren"], "123456789")
        self.assertEqual(card["denomination"], "ATELIER MARTIN")
        self.assertEqual(card["forme"], "SARL")
        self.assertIn("PARIS", card["adresse"])
        self.assertEqual(card["naf"], "43.32A")
        self.assertEqual(card["activite_suggeree"], "btp")
        self.assertNotIn("dirigeants", card)
        self.assertNotIn("finances", card)
        self.assertNotIn("SECRET", str(card))

    @patch("integrations.insee.httpx.get")
    def test_siret_keeps_the_matching_establishment(self, get):
        hit = dict(API_HIT)
        hit["siege"] = dict(API_HIT["siege"], siret="12345678900099", adresse="SIEGE LOINTAIN")
        hit["matching_etablissements"] = [{
            "siret": "12345678900012",
            "adresse": "12 RUE DES ARTISANS 75011 PARIS",
        }]
        get.return_value = _response(200, {"results": [hit]})
        results, error = search_entreprises("12345678900012")
        self.assertIsNone(error)
        self.assertEqual(results[0]["siret"], "12345678900012")
        self.assertIn("ARTISANS", results[0]["adresse"])

    @patch("integrations.insee.httpx.get")
    def test_rate_limit_and_outage(self, get):
        get.return_value = _response(429, {})
        results, error = search_entreprises("menuiserie")
        self.assertEqual(results, [])
        self.assertEqual(error, "rate_limit")

        cache.clear()
        get.side_effect = httpx.ConnectError("réseau")
        results, error = search_entreprises("menuiserie")
        self.assertEqual(error, "error")
        self.assertGreaterEqual(get.call_count, 1)

    @patch("integrations.insee.httpx.get")
    def test_transient_ssl_error_is_retried(self, get):
        get.side_effect = [
            httpx.ConnectError("eof"),
            _response(200, {"results": [API_HIT]}),
        ]
        results, error = search_entreprises("atelier martin")
        self.assertIsNone(error)
        self.assertEqual(results[0]["denomination"], "ATELIER MARTIN")

    @patch("integrations.insee.httpx.get")
    def test_official_card_uses_the_siren_cache(self, get):
        get.return_value = _response(200, {"results": [API_HIT]})
        search_entreprises("123456789")
        get.reset_mock()
        card, error = official_card("123456789")
        self.assertIsNone(error)
        self.assertEqual(card["denomination"], "ATELIER MARTIN")
        get.assert_not_called()

    def test_slim_hit_ignores_people(self):
        card = slim_annuaire_hit(API_HIT)
        self.assertNotIn("SECRET", str(card))
