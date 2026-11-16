"""Socle PWA : service worker racine, page hors-ligne, manifeste."""
from pathlib import Path

from django.conf import settings
from django.test import TestCase

STATIC_DIR = Path(settings.BASE_DIR) / "static"


class ServiceWorkerTests(TestCase):
    """Le SW est servi à la racine par vue Django (fonctionne en tests)."""

    def test_sw_served_at_root(self):
        response = self.client.get("/sw.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["Content-Type"],
            "application/javascript; charset=utf-8",
        )
        self.assertEqual(response.headers["Service-Worker-Allowed"], "/")
        body = response.content.decode()
        self.assertIn("rrs-pwa-", body)
        self.assertIn("offline.html", body)

    def test_sw_never_caches_pages(self):
        """Le SW ne doit pas mettre les pages (sessions/CSRF) en cache."""
        body = self.client.get("/sw.js").content.decode()
        self.assertIn('request.method !== "GET"', body)
        # Les pages ne sont jamais en cache-first : réseau -> offline.
        self.assertIn('request.mode === "navigate"', body)


class OfflinePageTests(TestCase):
    def test_offline_shell_exists_and_standalone(self):
        path = STATIC_DIR / "pwa" / "offline.html"
        self.assertTrue(path.exists())
        body = path.read_text(encoding="utf-8")
        self.assertIn("Vous êtes hors ligne", body)
        self.assertIn("navigator.onLine", body)


class ManifestTests(TestCase):
    def test_manifest_has_512_and_maskable(self):
        path = STATIC_DIR / "site.webmanifest"
        manifest = path.read_text(encoding="utf-8")
        self.assertIn("pwa-512.png", manifest)
        self.assertIn("maskable", manifest)
        self.assertIn('"display": "standalone"', manifest)

    def test_512_icon_file_exists(self):
        self.assertTrue((STATIC_DIR / "img" / "pwa-512.png").exists())
