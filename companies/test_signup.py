import json
import re
from datetime import date
from unittest.mock import patch
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings

from accounts.models import PendingSignup
from accounts.verification import normalize_french_phone, send_phone_verification
from companies.models import Company
from documents.models import Invoice
from accounting.models import JournalEntry
from integrations.tests import API_HIT, _response


WIZARD = {
    "denomination": "Atelier Martin",
    "forme": "SARL",
    "activites": ["btp"],
    "regime": "reel_simple",
    "tva": "reel",
    "exercice_debut": "2026-01-01",
    "email": "martin@exemple.fr",
    "phone": "06 12 34 56 78",
    "password1": "Cockpit-Lyonnais-2026",
    "password2": "Cockpit-Lyonnais-2026",
    "siren": "123456789",
}


@override_settings(SIGNUP_VERIFICATION_ENABLED=False)
class SignupFlowTests(TestCase):
    def setUp(self):
        cache.clear()

    def _mock_annuaire(self):
        return patch("integrations.insee.httpx.get", return_value=_response(200, {"results": [API_HIT]}))

    def test_home_starts_with_company_search_and_a_separate_demo(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="q"')
        self.assertContains(response, 'action="/recherche/"')
        self.assertContains(response, "Essayer la démo")
        self.assertContains(response, "/compte/demo/")
        self.assertContains(response, "J'ai déjà un compte")
        self.assertNotContains(response, "data-siren-search")

    def test_short_query_explains_what_to_type(self):
        response = self.client.get("/recherche/", {"q": "a"})
        self.assertContains(response, "SIREN")
        self.assertContains(response, "SIRET")

    def test_rate_limit_is_a_friendly_message(self):
        with patch("integrations.insee.httpx.get", return_value=_response(429, {})):
            response = self.client.get("/recherche/", {"q": "menuiserie"})
        self.assertContains(response, "très sollicité")
        self.assertNotContains(response, "429")

    def test_search_pick_wizard_opens_an_empty_cockpit(self):
        with self._mock_annuaire():
            results = self.client.get("/recherche/", {"q": "atelier martin"})
            self.assertContains(results, "ATELIER MARTIN")
            self.assertContains(results, "SARL")
            self.assertContains(results, "43.32A")
            self.assertContains(results, "12 RUE DES ARTISANS")
            chosen = self.client.get("/inscription/choisir/", {"siren": "123456789"})
        self.assertRedirects(chosen, "/inscription/", fetch_redirect_response=False)
        blob = json.dumps(self.client.session["signup_lookup"])
        self.assertNotIn("SECRET", blob)
        self.assertNotIn("dirigeants", blob)
        self.assertNotIn("finances", blob)
        self.assertLess(len(blob), 2000)

        page = self.client.get("/inscription/")
        self.assertContains(page, "ATELIER MARTIN")
        self.assertContains(page, "12 RUE DES ARTISANS")
        self.assertContains(page, "Créer mon cockpit")

        created = self.client.post("/inscription/", WIZARD)
        company = Company.objects.get(siren="123456789")
        self.assertRedirects(
            created,
            f"/cockpit/?societe={company.id}",
            fetch_redirect_response=False,
        )
        self.assertEqual(company.denomination, "Atelier Martin")
        self.assertEqual(company.owner.email, "martin@exemple.fr")
        self.assertEqual(company.owner.phone, "0612345678")
        self.assertTrue(company.owner.check_password("Cockpit-Lyonnais-2026"))
        self.assertNotIn("password", company.source_data)
        self.assertNotIn("Cockpit-Lyonnais-2026", str(company.source_data))
        self.assertFalse(company.owner.phone_verified)
        self.assertEqual(company.address, "12 RUE DES ARTISANS 75011 PARIS")
        self.assertEqual(company.code_naf, "4332A")
        self.assertEqual(company.regime, "reel_simple")
        self.assertEqual(company.tva, "reel")
        self.assertEqual(company.journals.count(), 5)
        self.assertTrue(company.accounts.filter(code="44566").exists())
        self.assertEqual(company.source_data["source"], "annuaire_entreprises")
        self.assertNotIn("raw", company.source_data)
        self.assertEqual(JournalEntry.objects.filter(company=company).count(), 0)
        self.assertEqual(Invoice.objects.filter(company=company).count(), 0)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Bienvenue", mail.outbox[0].subject)
        self.assertIn("martin@exemple.fr", mail.outbox[0].to)
        self.assertIn("Atelier Martin", mail.outbox[0].body)
        self.assertEqual(PendingSignup.objects.count(), 0)

        cockpit = self.client.get(created["Location"])
        self.assertEqual(cockpit.status_code, 200)
        self.assertContains(cockpit, "Atelier Martin")
        self.assertContains(cockpit, "123456789")
        self.assertContains(cockpit, "Aucune écriture validée")
        self.assertContains(cockpit, "Aucune facture ouverte")
        self.assertNotContains(cockpit, "Menuiserie Dupont")
        self.assertNotContains(cockpit, "FAC-2026-00042")
        self.assertNotContains(cockpit, "Cadres Industries")

    def test_known_siren_offers_login_and_does_not_duplicate(self):
        owner = get_user_model().objects.create_user("deja@exemple.fr")
        Company.objects.create(
            owner=owner,
            siren="123456789",
            denomination="Déjà là",
            forme="SARL",
            regime="reel_simple",
            tva="reel",
            exercice_debut=date(2026, 1, 1),
        )
        with self._mock_annuaire():
            self.client.get("/inscription/choisir/", {"siren": "123456789"})
        page = self.client.get("/inscription/")
        self.assertContains(page, "déjà rattachée")
        self.assertContains(page, "/compte/")
        posted = self.client.post("/inscription/", WIZARD)
        self.assertEqual(posted.status_code, 200)
        self.assertEqual(Company.objects.filter(siren="123456789").count(), 1)
        self.assertFalse(get_user_model().objects.filter(email="martin@exemple.fr").exists())

    def test_existing_email_receives_the_new_company(self):
        get_user_model().objects.create_user("martin@exemple.fr")
        with self._mock_annuaire():
            self.client.get("/inscription/choisir/", {"siren": "123456789"})
        self.client.post("/inscription/", WIZARD)
        self.assertEqual(get_user_model().objects.filter(email="martin@exemple.fr").count(), 1)
        company = Company.objects.get(siren="123456789")
        self.assertEqual(company.owner.email, "martin@exemple.fr")
        cockpit = self.client.get(f"/cockpit/?societe={company.id}")
        self.assertContains(cockpit, "Atelier Martin")

    def test_logged_in_user_adds_the_company_through_onboarding(self):
        user = get_user_model().objects.create_user("dirigeant@exemple.fr")
        self.client.force_login(user)
        with self._mock_annuaire():
            response = self.client.get("/inscription/choisir/", {"siren": "123456789"})
        self.assertRedirects(response, "/ajouter/confirmer/", fetch_redirect_response=False)
        lookup = json.dumps(self.client.session["onboarding_lookup"])
        self.assertNotIn("SECRET", lookup)
        page = self.client.get("/ajouter/confirmer/")
        self.assertContains(page, "ATELIER MARTIN")
        saved = self.client.post("/ajouter/confirmer/", {
            "denomination": "Atelier Martin",
            "forme": "SARL",
            "activites": ["btp"],
            "regime": "micro",
            "tva": "franchise",
            "exercice_debut": "2026-01-01",
        })
        company = Company.objects.get(siren="123456789")
        self.assertEqual(company.owner, user)
        self.assertEqual(company.regime, "micro")
        self.assertEqual(company.journals.count(), 2)
        self.assertFalse(company.accounts.filter(code="44566").exists())
        self.assertRedirects(
            saved,
            f"/cockpit/?societe={company.id}",
            fetch_redirect_response=False,
        )

    def test_password_mismatch_does_not_create_the_account(self):
        with self._mock_annuaire():
            self.client.get("/inscription/choisir/", {"siren": "123456789"})
        response = self.client.post("/inscription/", dict(WIZARD, password2="Autre-Chose-2026"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ne correspondent pas")
        self.assertFalse(Company.objects.filter(siren="123456789").exists())
        self.assertFalse(get_user_model().objects.filter(email="martin@exemple.fr").exists())

    def test_invalid_phone_does_not_create_anything(self):
        with self._mock_annuaire():
            self.client.get("/inscription/choisir/", {"siren": "123456789"})
        payload = dict(WIZARD, phone="abc")
        response = self.client.post("/inscription/", payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "10 chiffres")
        self.assertFalse(Company.objects.filter(siren="123456789").exists())


@override_settings(SIGNUP_VERIFICATION_ENABLED=True)
class SignupVerificationTests(TestCase):
    def setUp(self):
        cache.clear()

    def _reach_wizard(self):
        with patch("integrations.insee.httpx.get", return_value=_response(200, {"results": [API_HIT]})):
            self.client.get("/inscription/choisir/", {"siren": "123456789"})

    def test_flag_sends_the_link_and_does_not_create_the_company_yet(self):
        self._reach_wizard()
        page = self.client.get("/inscription/")
        self.assertContains(page, "Continuer")
        response = self.client.post("/inscription/", WIZARD)
        self.assertRedirects(response, "/inscription/verifier/", fetch_redirect_response=False)
        self.assertFalse(Company.objects.filter(siren="123456789").exists())
        self.assertFalse(get_user_model().objects.filter(email="martin@exemple.fr").exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("martin@exemple.fr", mail.outbox[0].to)
        waiting = self.client.get("/inscription/verifier/")
        self.assertContains(waiting, "martin@exemple.fr")
        self.assertContains(waiting, "aucun opérateur")

        match = re.search(r"https?://\S+", mail.outbox[0].body)
        self.assertIsNotNone(match)
        done = self.client.get(urlparse(match.group(0)).path)
        company = Company.objects.get(siren="123456789")
        self.assertRedirects(
            done,
            f"/cockpit/?societe={company.id}",
            fetch_redirect_response=False,
        )
        cockpit = self.client.get(done["Location"])
        self.assertContains(cockpit, "Atelier Martin")
        self.assertContains(cockpit, "Aucune facture ouverte")
        self.assertNotContains(cockpit, "Menuiserie Dupont")
        self.assertEqual(company.journals.count(), 5)
        self.assertTrue(company.owner.check_password("Cockpit-Lyonnais-2026"))
        self.assertNotIn("Cockpit-Lyonnais-2026", mail.outbox[0].body)

    def test_phone_code_is_checked_when_a_provider_would_send_it(self):
        raw, code, pending = PendingSignup.issue(
            email="martin@exemple.fr",
            phone="0612345678",
            siren="123456789",
            payload={
                "siren": "123456789",
                "denomination": "Atelier Martin",
                "forme": "SARL",
                "adresse": "12 RUE DES ARTISANS 75011 PARIS",
                "code_naf": "4332A",
                "activites": ["btp"],
                "regime": "reel_simple",
                "tva": "franchise",
                "exercice_debut": "2026-01-01",
            },
        )
        session = self.client.session
        session["signup_pending_id"] = pending.pk
        session["signup_sms_sent"] = True
        session.save()
        # Session cookie signée : le client ne voit la nouvelle valeur qu'après
        # réécriture explicite du cookie (pas de table de sessions).
        self.client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
        wrong = self.client.post("/inscription/telephone/", {"code": "000000"})
        self.assertRedirects(wrong, "/inscription/verifier/", fetch_redirect_response=False)
        pending.refresh_from_db()
        self.assertFalse(pending.phone_verified)
        ok = self.client.post("/inscription/telephone/", {"code": code})
        self.assertRedirects(ok, "/inscription/verifier/", fetch_redirect_response=False)
        pending.refresh_from_db()
        self.assertTrue(pending.phone_verified)

        done = self.client.get(f"/inscription/verifier/{raw}/")
        self.assertEqual(done.status_code, 302)
        user = get_user_model().objects.get(email="martin@exemple.fr")
        self.assertTrue(user.phone_verified)
        self.assertEqual(Company.objects.get(siren="123456789").tva, "franchise")
        self.assertFalse(Company.objects.get(siren="123456789").accounts.filter(code="44566").exists())

    def test_sms_hook_does_not_send(self):
        self.assertFalse(send_phone_verification("0612345678", "123456"))
        self.assertEqual(normalize_french_phone("+33 6 12 34 56 78"), "0612345678")
