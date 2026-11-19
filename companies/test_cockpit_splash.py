"""Écran d'ouverture du cockpit : gabarit seulement, une fois par session."""
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase


class CockpitSplashTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("splash@exemple.fr")
        self.client.force_login(user)

    def test_cockpit_includes_the_session_splash(self):
        page = self.client.get("/cockpit/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'id="cockpit-splash"')
        self.assertContains(page, "cockpit-splash.css")
        self.assertContains(page, "cockpit-splash.js")
        self.assertContains(page, "rrs-cockpit-splash")
        self.assertContains(page, "img/logo.png")
        self.assertContains(page, "« Chargement des factures… »")
        self.assertContains(page, 'aria-live="polite"')
        self.assertContains(page, 'role="progressbar"')
        self.assertNotContains(page, "img/dark/mark.png")

        js = Path(settings.BASE_DIR, "static/js/cockpit-splash.js").read_text(encoding="utf-8")
        self.assertIn("var SPLASH_MS = 10000;", js)
        for message in (
            "« Chargement des factures… »",
            "« Chargement des clients… »",
            "« Chargement du bureau… »",
            "« Préparation de votre cockpit… »",
            "« Prêt ! »",
        ):
            self.assertIn(message, js)
        self.assertIn("prefers-reduced-motion", js)

        css = Path(settings.BASE_DIR, "static/css/cockpit-splash.css").read_text(encoding="utf-8")
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("#7a3cff", css)

    def test_splash_is_only_on_the_main_cockpit(self):
        for url in ("/cockpit/global/", "/aide/"):
            page = self.client.get(url)
            self.assertEqual(page.status_code, 200, url)
            self.assertNotContains(page, 'id="cockpit-splash"')
        settings_page = self.client.get("/societe/")
        self.assertNotIn('id="cockpit-splash"', settings_page.content.decode())

    def test_dark_cockpit_keeps_its_mark_and_shows_the_splash(self):
        page = self.client.get("/dark/cockpit/")
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        self.assertIn('id="cockpit-splash"', body)
        self.assertIn("img/logo.png", body)
        self.assertIn("img/dark/mark.png", body)
        self.assertNotIn("img/logo-96.png", body)
