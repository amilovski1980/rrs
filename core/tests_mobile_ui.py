"""Tests du shell mobile — régressions UI détectées en local.

Contexte : revue design mobile (viewport 390×844) du 15/11/2026.
Ces tests gardent en échec les bugs vus à cette occasion :

- NoReverseMatch 'history_import' sur /factures/ (urls jamais inclues) ;
- bandeau démo affiché en double (banner statique + message flash) ;
- viewport avec `user-scalable=no` (WCAG 1.4.4) ;
- shell mobile (m-header / m-footer) présent sur l'app authentifiée.
"""
from django.test import TestCase
from django.urls import reverse


class MobileShellTests(TestCase):
    """Le shell mobile est rendu sur les pages authentifiées."""

    def setUp(self):
        self.client.get(reverse("demo_login"))  # cockpit démo, lecture seule

    def test_cockpit_serves_the_mobile_shell(self):
        response = self.client.get(reverse("cockpit"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        for marker in (
            "data-m-header",      # header fixe mobile
            "data-nav-toggle",    # bouton du drawer
            "data-m-footer",      # dock de raccourcis
            "m-header", "m-footer",
        ):
            self.assertIn(marker, content, f"Shell mobile : marqueur absent « {marker} »")

    def test_viewport_meta_allows_zoom(self):
        # WCAG 1.4.4 : l'utilisateur doit pouvoir zoomer.
        response = self.client.get(reverse("cockpit"))
        head = response.content.decode()
        self.assertIn("viewport-fit=cover", head)
        self.assertNotIn("user-scalable=no", head)
        self.assertNotIn("maximum-scale=1", head)


class DemoBannerTests(TestCase):
    """Le bandeau démo ne doit apparaître qu'une fois par page."""

    def test_demo_banner_not_duplicated(self):
        self.client.get(reverse("demo_login"))
        response = self.client.get(reverse("cockpit"))
        content = response.content.decode()
        self.assertIn("demo-readonly-banner", content)
        self.assertEqual(
            content.lower().count("lecture seule"),
            1,
            "Le bandeau démo est dupliqué (banner statique + flash).",
        )


class HistoryImportNamespaceTests(TestCase):
    """Régression : /factures/ plantait sans le namespace history_import.

    Les gabarits (base.html, invoice_dashboard.html, purchases/dashboard.html…)
    font `{% url 'history_import:upload' %}` dès que le forfait le permet ;
    config/urls.py doit donc inclure history_import.urls, sinon NoReverseMatch.
    """

    def test_namespace_is_registered(self):
        self.assertEqual(reverse("history_import:upload"), "/migration/")

    def test_invoice_pages_render(self):
        self.client.get(reverse("demo_login"))
        # /factures/ fait le rendu du bouton « Importer plusieurs factures »
        self.assertEqual(self.client.get(reverse("invoices")).status_code, 200)
        self.assertEqual(self.client.get(reverse("invoice_list")).status_code, 200)
        # /achats/ rend « Importer des factures fournisseurs »
        self.assertEqual(self.client.get(reverse("purchases:dashboard")).status_code, 200)


class MobileSmokeTests(TestCase):
    """Parcours principal en viewport mobile : toutes les pages passent en 200.

    Détection générique : Django renvoie le debug NoReverseMatch en 500
    en développement, couvert ici par l'assertion de statut.
    """

    def setUp(self):
        self.client.get(reverse("demo_login"))

    def test_main_pages_render_at_200(self):
        pages = [
            reverse("cockpit"),
            reverse("invoices"),
            reverse("invoice_list"),
            reverse("invoice_create"),
            reverse("clients"),
            reverse("contacts"),
            reverse("ledger"),
            reverse("balance"),
            reverse("entry_create"),
            reverse("purchases:dashboard"),
            reverse("banking:dashboard"),
            reverse("treasury:dashboard"),
        ]
        for url in pages:
            with self.subTest(url=url):
                response = self.client.get(url, follow=True)
                self.assertEqual(
                    response.status_code,
                    200,
                    f"{url} ne répond pas en 200 (erreur de rendu ?)",
                )
                self.assertNotIn(b"NoReverseMatch", response.content)
