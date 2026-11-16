"""Échéances du cockpit : calendrier dérivé du profil de la société."""
from datetime import date

from django.test import TestCase

from companies.deadlines import upcoming
from companies.models import Company
from django.contrib.auth import get_user_model


def _company(regime="reel_simple", tva="reel", exercice_debut=date(2025, 12, 1)):
    user = get_user_model().objects.create_user(f"ech-{abs(hash(regime + tva + str(exercice_debut)))}@exemple.fr")
    return Company.objects.create(
        owner=user,
        siren=f"{abs(hash(regime + tva + str(exercice_debut))) % 100000000:08d}0"[:9],
        denomination="Échéances SARL",
        forme="SARL",
        regime=regime,
        tva=tva,
        exercice_debut=exercice_debut,
    )


class DeadlinesTests(TestCase):
    def test_franchise_has_no_tva_rows(self):
        company = _company(tva="franchise")
        items = upcoming(company, today=date(2026, 11, 16))
        self.assertFalse([i for i in items if i["kind"] == "tva"])
        labels = [i["label"] for i in items]
        self.assertIn("CFE — paiement de la cotisation", labels)
        self.assertIn("Clôture de l'exercice", labels)

    def test_tva_rows_when_assujetti(self):
        company = _company(tva="reel")
        items = upcoming(company, today=date(2026, 11, 16))
        tva_labels = [i["label"] for i in items if i["kind"] == "tva"]
        self.assertTrue(tva_labels)
        # la prochaine échéance TVA après le 16/11/2026 = 24/01/2027 (T4)
        first = next(i for i in items if i["kind"] == "tva")
        self.assertEqual(first["date"], date(2027, 1, 24))
        self.assertIn("T4", first["label"])

    def test_cfe_declaration_for_creation_year(self):
        company = _company(exercice_debut=date(2026, 3, 1))
        items = upcoming(company, today=date(2026, 6, 1))
        labels = [i["label"] for i in items]
        self.assertIn("CFE — déclaration initiale 1447-C", labels)

    def test_sorted_and_urgent_flag(self):
        company = _company(exercice_debut=date(2026, 12, 5), tva="franchise")
        items = upcoming(company, today=date(2026, 11, 16))
        dates = [i["date"] for i in items]
        self.assertEqual(dates, sorted(dates))
        # Une clôture tombe à ~1 an (anniversaire du début d'exercice) :
        # jamais "bientôt". La CFE du 15/12/2026 est à 29 j → "soon".
        close = next(i for i in items if i["kind"] == "cloture")
        self.assertGreater(close["days"], 45)
        cfe = next(i for i in items if "cotisation" in i["label"])
        self.assertEqual(cfe["date"], date(2026, 12, 15))
        self.assertTrue(cfe["soon"])

    def test_never_in_the_past(self):
        company = _company(exercice_debut=date(2024, 12, 1))
        today = date(2026, 11, 16)
        items = upcoming(company, today=today)
        self.assertTrue(all(i["date"] >= today for i in items))
