from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Company


class CompanySettingsTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("atelier@exemple.fr")
        self.company = Company.objects.create(
            owner=user,
            siren="812345679",
            denomination="Atelier Test",
            forme="SARL",
            regime="reel_simple",
            tva="reel",
            exercice_debut=date(2026, 1, 1),
            address="1 rue du Bois 75011 Paris",
        )
        self.client.force_login(user)

    def test_settings_save_phone_and_theme(self):
        page = self.client.get("/societe/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "1 rue du Bois")
        saved = self.client.post("/societe/", {
            "denomination": "Atelier Test",
            "forme": "SARL",
            "address": "12 rue des Artisans 75011 Paris",
            "phone": "06 12 34 56 78",
            "email": "compta@atelier.fr",
            "invoice_theme": "carmin",
        })
        self.assertEqual(saved.status_code, 302)
        self.company.refresh_from_db()
        self.assertEqual(self.company.phone, "06 12 34 56 78")
        self.assertEqual(self.company.invoice_theme, "carmin")
        self.assertIn("Artisans", self.company.address)

    def test_theme_switch_from_invoice_page(self):
        response = self.client.post("/societe/", {
            "theme": "encre",
            "next": "/cockpit/",
        })
        self.assertRedirects(response, "/cockpit/", fetch_redirect_response=False)
        self.company.refresh_from_db()
        self.assertEqual(self.company.invoice_theme, "encre")


    def test_new_invoice_themes_listed(self):
        page = self.client.get("/societe/")
        self.assertEqual(page.status_code, 200)
        for label in ("Graphite", "Indigo", "Terra"):
            self.assertContains(page, label)

    def test_accepts_graphite_theme(self):
        response = self.client.post("/societe/", {
            "theme": "graphite",
            "next": "/cockpit/",
        })
        self.assertEqual(response.status_code, 302)
        self.company.refresh_from_db()
        self.assertEqual(self.company.invoice_theme, "graphite")



class LandingPageTests(TestCase):
    def test_home_renders_without_utility_bar(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'class="utility"')
        self.assertNotContains(response, "utility-in")
        self.assertContains(response, 'class="nav"')




class LogoBrandTests(TestCase):
    """Le logo produit Road Runner est le PNG (plus de logo.svg)."""

    def setUp(self):
        user = get_user_model().objects.create_user("logo@exemple.fr")
        self.user = user
        self.company = Company.objects.create(
            owner=user,
            siren="866666666",
            denomination="Logo SARL",
            forme="SARL",
            regime="reel_simple",
            tva="reel",
            exercice_debut=date(2026, 1, 1),
        )
        self.client.force_login(user)

    def _assert_png_logo(self, response):
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("img/logo.png", body)
        self.assertNotIn("logo.svg", body)
        self.assertNotIn("img/logo.svg", body)

    def test_landing_uses_png_logo(self):
        self._assert_png_logo(self.client.get("/"))

    def test_cockpit_uses_png_logo(self):
        self._assert_png_logo(self.client.get(f"/cockpit/?societe={self.company.id}"))

    def test_login_uses_png_logo(self):
        self.client.logout()
        self._assert_png_logo(self.client.get("/compte/"))

    def test_static_logo_png_is_served(self):
        from django.contrib.staticfiles.finders import find
        path = find("img/logo.png")
        self.assertIsNotNone(path)
        self.assertTrue(path.endswith("logo.png"))
        self.assertIsNone(find("img/logo.svg"))


class CompanyColorTagTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("couleurs@exemple.fr")
        self.user = user
        self.companies = []
        for i, name in enumerate(["Alpha SARL", "Beta SAS", "Gamma EURL"]):
            self.companies.append(
                Company.objects.create(
                    owner=user,
                    siren=f"81234568{i}",
                    denomination=name,
                    forme="SARL",
                    regime="reel_simple",
                    tva="reel",
                    exercice_debut=date(2026, 1, 1),
                    address="1 rue Test 75011 Paris",
                )
            )
        self.client.force_login(user)

    def test_cockpit_company_cards_have_distinct_color_classes(self):
        page = self.client.get(f"/cockpit/?societe={self.companies[0].id}")
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        found = []
        for i in range(10):
            if f"company co-c{i}" in body or f"company co-c{i} " in body:
                found.append(i)
        # Au moins 3 pastilles distinctes pour 3 sociétés
        classes = []
        for c in self.companies:
            # classe attribuée par index dans la liste
            from companies.templatetags.company_colors import company_color_class
            classes.append(company_color_class(c, self.companies))
        self.assertEqual(len(set(classes)), 3)
        for cls in classes:
            self.assertIn(cls, body)
        self.assertIn("co-avatar", body)

    def test_color_class_stable_by_id(self):
        from companies.templatetags.company_colors import company_color_class
        a = company_color_class(self.companies[0])
        b = company_color_class(self.companies[0])
        self.assertEqual(a, b)
        self.assertRegex(a, r"^co-c[0-9]$")


class MobileNavChromeTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("mobnav@exemple.fr")
        self.user = user
        self.company = Company.objects.create(
            owner=user,
            siren="877777777",
            denomination="Nav Mobile SARL",
            forme="SARL",
            regime="reel_simple",
            tva="reel",
            exercice_debut=date(2026, 1, 1),
            address="1 rue Mobile 75011 Paris",
        )
        self.client.force_login(user)

    def test_cockpit_has_mobile_header_drawer_footer(self):
        page = self.client.get(f"/cockpit/?societe={self.company.id}")
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        self.assertIn('data-m-header', body)
        self.assertIn('data-nav-toggle', body)
        self.assertIn('aria-controls="app-drawer"', body)
        self.assertIn('aria-expanded="false"', body)
        self.assertIn('id="app-drawer"', body)
        self.assertIn('data-app-drawer', body)
        self.assertIn('data-nav-backdrop', body)
        self.assertIn('data-nav-close', body)
        self.assertIn('data-m-footer', body)
        # Liens principaux du drawer
        for label in (
            "Cockpit",
            "Factures",
            "Clients",
            "Devis",
            "Avoirs",
            "Paiements",
            "Projets",
            "Catalogue",
            "Tickets de caisse",
            "Grand livre",
            "Balance",
        ):
            self.assertIn(label, body)
        # Footer
        self.assertIn("Mon compte", body)
        self.assertIn("Paramètres", body)
        self.assertIn("Aide", body)
        self.assertIn("Mentions", body)
        self.assertIn("/compte/profil/", body)
        self.assertIn("/societe/", body)
        self.assertIn("/aide/", body)
        self.assertIn("/mentions-legales/", body)
        # Page courante mise en avant
        self.assertIn('side-link active', body)

    def test_help_requires_login_and_renders(self):
        anon = self.client
        anon.logout()
        denied = anon.get("/aide/")
        self.assertEqual(denied.status_code, 302)
        self.assertIn("/compte/", denied["Location"])
        self.client.force_login(self.user)
        ok = self.client.get("/aide/")
        self.assertEqual(ok.status_code, 200)
        self.assertContains(ok, "Aide")
        self.assertContains(ok, "Tickets de caisse")

    def test_legal_notice_public_placeholders(self):
        anon = self.client
        anon.logout()
        page = anon.get("/mentions-legales/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Mentions légales")
        self.assertContains(page, "À compléter")
        self.assertContains(page, "placeholders")

    def test_invoices_page_keeps_mobile_chrome(self):
        page = self.client.get(f"/factures/?societe={self.company.id}")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'data-nav-toggle')
        self.assertContains(page, 'data-m-footer')
        self.assertContains(page, "Factures")
