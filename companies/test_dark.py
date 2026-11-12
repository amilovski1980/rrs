"""La vitrine /dark est une autre voix. L'accueil / reste celui des bâtisseurs."""
import re
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import urlparse

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings

from billing.models import Plan
from companies.models import Company
from companies.test_signup import WIZARD
from integrations.tests import API_HIT, _response

PASSWORD = "Cockpit-Lyonnais-2026"


def _annuaire():
    return patch("integrations.insee.httpx.get", return_value=_response(200, {"results": [API_HIT]}))


class DarkRoutingTests(TestCase):
    def test_dark_home_is_the_startup_design(self):
        response = self.client.get("/dark/")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("dark.css", body)
        self.assertIn("Outfit", body)
        self.assertIn("img/dark/mark.png", body)
        self.assertIn("img/dark/wordmark.png", body)
        self.assertIn("img/dark/favicon-48.png", body)
        self.assertIn("La compta de votre startup", body)
        self.assertIn("tenue nette", body)
        self.assertIn('id="pricing"', body)
        self.assertIn('id="recherche"', body)
        self.assertIn('action="/dark/recherche/"', body)
        self.assertIn('href="/dark/compte/"', body)
        self.assertIn("btn-green", body)
        self.assertIn('data-plan="reel"', body)
        self.assertIn("Je me lance", body)
        self.assertIn("Pour ouvrir la boîte", body)
        self.assertIn("29 €", body)
        self.assertIn("49 €", body)
        self.assertIn("79 €", body)
        self.assertIn("HT / mois", body)
        self.assertIn("1 société", body)
        self.assertIn("3 sociétés", body)
        self.assertIn("20 factures / mois", body)
        self.assertIn("Sociétés illimitées", body)
        self.assertIn("Tickets de caisse", body)
        self.assertIn("Voix Aminia", body)
        self.assertIn("Tarifs mensuels hors taxes", body)
        self.assertIn("Le montant débité correspond au prix affiché.", body)
        self.assertIn("Sans carte bancaire · 14 jours pour tester", body)
        self.assertNotIn("app.css", body)
        self.assertNotIn("bâtisseur", body.lower())
        self.assertNotIn("enfin sans friction", body)
        self.assertNotIn("Commencer l'essai", body)
        self.assertNotIn("img/logo", body)
        self.assertEqual(Plan.objects.count(), 0)

    def test_classic_home_keeps_its_design_and_copy(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("app.css", body)
        self.assertIn("Roboto", body)
        self.assertIn("La comptabilité de vos sociétés", body)
        self.assertIn("enfin sans friction", body)
        self.assertIn("Conçu pour les bâtisseurs", body)
        self.assertIn("Un prix simple, par bâtisseur", body)
        self.assertIn('action="/recherche/"', body)
        self.assertContains(
            response,
            '<a class="btn btn-lg btn-primary" href="#recherche">Commencer l\'essai</a>',
            html=True,
        )
        self.assertIn("img/logo", body)
        self.assertNotIn("dark.css", body)
        self.assertNotIn("Outfit", body)
        self.assertNotIn("img/dark/", body)
        self.assertNotIn("La compta de votre startup", body)
        self.assertNotIn("tenue nette", body)

    def test_published_blurb_is_kept_on_dark(self):
        Plan.objects.create(
            code="micro",
            name="Micro",
            price_eur=Decimal("29.00"),
            description="Offre rédigée dans le back-office.",
            is_active=True,
            trial_days=14,
        )
        response = self.client.get("/dark/")
        self.assertContains(response, "Offre rédigée dans le back-office.")
        self.assertContains(response, "29 €")
        self.assertNotContains(response, "Pour ouvrir la boîte")

    def test_dark_assets_exist(self):
        from django.contrib.staticfiles.finders import find

        for name in ("img/dark/mark.png", "img/dark/wordmark.png", "img/dark/favicon-48.png", "css/dark.css"):
            self.assertIsNotNone(find(name), name)


class DarkSearchSignupLoginTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_empty_search_returns_to_its_own_home(self):
        dark = self.client.get("/dark/recherche/")
        self.assertRedirects(dark, "/dark/", fetch_redirect_response=False)
        classic = self.client.get("/recherche/")
        self.assertRedirects(classic, "/", fetch_redirect_response=False)

    def test_dark_search_explains_and_stays_dark(self):
        response = self.client.get("/dark/recherche/", {"q": "a"})
        self.assertContains(response, "SIREN")
        self.assertContains(response, "SIRET")
        self.assertContains(response, "dark.css")
        self.assertContains(response, "Laquelle est la vôtre")
        self.assertNotContains(response, "app.css")

    def test_classic_search_copy_is_unchanged(self):
        response = self.client.get("/recherche/", {"q": "a"})
        self.assertContains(response, "Choisissez votre société")
        self.assertNotContains(response, "dark.css")
        self.assertNotContains(response, "Laquelle est la vôtre")

    @override_settings(SIGNUP_VERIFICATION_ENABLED=False)
    def test_search_signup_and_login_from_dark(self):
        with _annuaire():
            results = self.client.get("/dark/recherche/", {"q": "atelier martin"})
            self.assertContains(results, "ATELIER MARTIN")
            self.assertContains(results, 'href="/dark/inscription/choisir/?siren=123456789"')
            self.assertNotContains(results, 'href="/inscription/')
            chosen = self.client.get("/dark/inscription/choisir/", {"siren": "123456789"})
        self.assertRedirects(chosen, "/dark/inscription/", fetch_redirect_response=False)
        page = self.client.get("/dark/inscription/")
        self.assertContains(page, "C'est bien cette société")
        self.assertContains(page, "Mot de passe")
        self.assertContains(page, "Huit caractères minimum")
        self.assertContains(page, "ATELIER MARTIN")
        self.assertContains(page, "dark.css")
        self.assertNotContains(page, "Confirmez votre société")

        created = self.client.post("/dark/inscription/", WIZARD)
        company = Company.objects.get(siren="123456789")
        self.assertRedirects(
            created,
            f"/cockpit/?societe={company.id}",
            fetch_redirect_response=False,
        )
        self.assertTrue(company.owner.check_password(PASSWORD))
        self.assertEqual(company.journals.count(), 5)
        cockpit = self.client.get(created["Location"])
        self.assertContains(cockpit, "Atelier Martin")
        self.assertNotContains(cockpit, "dark.css")

        self.client.logout()
        login_page = self.client.get("/dark/compte/")
        self.assertContains(login_page, "Content de vous revoir")
        self.assertContains(login_page, "dark.css")
        bad = self.client.post("/dark/compte/", {"email": "martin@exemple.fr", "password": "mauvais-mot"})
        self.assertContains(bad, "Email ou mot de passe incorrect")
        self.assertContains(bad, "dark.css")
        ok = self.client.post("/dark/compte/", {"email": "martin@exemple.fr", "password": PASSWORD})
        self.assertRedirects(ok, "/cockpit/", fetch_redirect_response=False)

    def test_classic_login_copy_is_unchanged(self):
        page = self.client.get("/compte/")
        self.assertContains(page, "Email et mot de passe du cockpit")
        self.assertContains(page, "app.css")
        self.assertNotContains(page, "dark.css")
        self.assertNotContains(page, "Content de vous revoir")

    def test_logged_in_pick_uses_the_existing_onboarding(self):
        user = get_user_model().objects.create_user("dirigeant@exemple.fr", password=PASSWORD)
        self.client.force_login(user)
        with _annuaire():
            response = self.client.get("/dark/inscription/choisir/", {"siren": "123456789"})
        self.assertRedirects(response, "/ajouter/confirmer/", fetch_redirect_response=False)
        page = self.client.get("/ajouter/confirmer/")
        self.assertContains(page, "ATELIER MARTIN")
        self.assertNotContains(page, "dark.css")

    @override_settings(SIGNUP_VERIFICATION_ENABLED=True)
    def test_verification_email_stays_on_dark(self):
        with _annuaire():
            self.client.get("/dark/inscription/choisir/", {"siren": "123456789"})
        response = self.client.post("/dark/inscription/", WIZARD)
        self.assertRedirects(response, "/dark/inscription/verifier/", fetch_redirect_response=False)
        self.assertFalse(Company.objects.filter(siren="123456789").exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/dark/inscription/verifier/", mail.outbox[0].body)
        waiting = self.client.get("/dark/inscription/verifier/")
        self.assertContains(waiting, "dark.css")
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
        self.assertTrue(company.owner.check_password(PASSWORD))


class DarkPasswordResetTests(TestCase):
    def test_reset_from_dark_stays_dark_and_classic_does_not(self):
        get_user_model().objects.create_user("fondateur@exemple.fr")
        sent = self.client.post("/dark/compte/mot-de-passe/oublie/", {"email": "fondateur@exemple.fr"})
        self.assertRedirects(sent, "/dark/compte/mot-de-passe/envoye/", fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/dark/compte/mot-de-passe/", mail.outbox[0].body)
        done = self.client.get("/dark/compte/mot-de-passe/envoye/")
        self.assertContains(done, "dark.css")
        self.assertContains(done, "Regardez vos mails")

        path = urlparse(re.search(r"https?://\S+", mail.outbox[0].body).group(0)).path
        self.assertTrue(path.startswith("/dark/compte/mot-de-passe/"))
        opened = self.client.get(path)
        self.assertEqual(opened.status_code, 302)
        form = self.client.get(opened.url)
        self.assertContains(form, "dark.css")
        self.assertContains(form, "Choisissez un mot de passe")
        saved = self.client.post(opened.url, {
            "new_password1": PASSWORD,
            "new_password2": PASSWORD,
        })
        self.assertRedirects(saved, "/dark/compte/mot-de-passe/modifie/", fetch_redirect_response=False)
        complete = self.client.get("/dark/compte/mot-de-passe/modifie/")
        self.assertContains(complete, "dark.css")
        user = get_user_model().objects.get(email="fondateur@exemple.fr")
        self.assertTrue(user.check_password(PASSWORD))

        mail.outbox.clear()
        classic = self.client.post("/compte/mot-de-passe/oublie/", {"email": "fondateur@exemple.fr"})
        self.assertRedirects(classic, "/compte/mot-de-passe/envoye/", fetch_redirect_response=False)
        self.assertNotIn("/dark/", mail.outbox[0].body)
        classic_page = self.client.get("/compte/mot-de-passe/envoye/")
        self.assertNotContains(classic_page, "dark.css")
        self.assertContains(classic_page, "Vérifiez votre boîte mail")
