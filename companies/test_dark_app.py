"""Le cockpit et l'admin sous /dark reprennent le même métier, avec l'habillage sombre."""
from django.contrib.auth import get_user_model
from django.test import TestCase

PASSWORD = "Cockpit-Lyonnais-2026"


class DarkApplicationTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.client_user = user_model.objects.create_user("client-dark@exemple.fr", password=PASSWORD)
        self.staff = user_model.objects.create_user(
            "staff-dark@exemple.fr", password=PASSWORD, is_staff=True,
        )

    def test_light_home_and_cockpit_keep_the_original_chrome(self):
        home = self.client.get("/")
        self.assertContains(home, "enfin sans friction")
        self.assertContains(home, "app.css")
        self.assertNotContains(home, "dark-app.css")
        self.assertNotContains(home, 'data-theme="dark"')

        self.client.force_login(self.client_user)
        cockpit = self.client.get("/cockpit/")
        self.assertEqual(cockpit.status_code, 200)
        self.assertContains(cockpit, "img/logo-96.png")
        self.assertContains(cockpit, "Ajoutez une société")
        self.assertNotContains(cockpit, "dark-app.css")
        self.assertNotContains(cockpit, 'data-theme="dark"')
        self.assertNotContains(cockpit, "img/dark/mark.png")

    def test_dark_cockpit_and_inner_pages_use_the_dark_layout(self):
        self.client.force_login(self.client_user)
        cockpit = self.client.get("/dark/cockpit/")
        self.assertEqual(cockpit.status_code, 200)
        body = cockpit.content.decode()
        self.assertIn("dark-app.css", body)
        self.assertIn('data-theme="dark"', body)
        self.assertIn("img/dark/mark.png", body)
        self.assertIn("img/dark/wordmark.png", body)
        self.assertIn("Outfit", body)
        self.assertIn('href="/dark/factures/"', body)
        self.assertIn('href="/dark/compta/grand-livre/"', body)
        self.assertIn('action="/dark/compte/logout/"', body)
        self.assertIn("Ajoutez une société", body)
        self.assertNotIn("img/logo-96.png", body)

        invoices = self.client.get("/dark/factures/")
        self.assertEqual(invoices.status_code, 302)
        self.assertTrue(invoices["Location"].startswith("/dark/"))

        chat = self.client.get("/dark/agent/chat/")
        self.assertIn(chat.status_code, (200, 302))
        if chat.status_code == 302:
            self.assertTrue(chat["Location"].startswith("/dark/"))
        else:
            self.assertContains(chat, "dark-app.css")

    def test_login_from_dark_continues_in_the_dark_cockpit(self):
        signed = self.client.post("/dark/compte/", {
            "email": "client-dark@exemple.fr",
            "password": PASSWORD,
        })
        self.assertRedirects(signed, "/dark/cockpit/", fetch_redirect_response=False)
        page = self.client.get(signed["Location"])
        self.assertContains(page, "dark-app.css")
        logged_out = self.client.post("/dark/compte/logout/")
        self.assertRedirects(logged_out, "/dark/compte/", fetch_redirect_response=False)
        login = self.client.get("/dark/compte/")
        self.assertContains(login, "dark.css")
        self.assertNotContains(login, "dark-app.css")

    def test_light_login_still_opens_the_light_cockpit(self):
        signed = self.client.post("/compte/", {
            "email": "client-dark@exemple.fr",
            "password": PASSWORD,
        })
        self.assertRedirects(signed, "/cockpit/", fetch_redirect_response=False)

    def test_anonymous_dark_cockpit_returns_to_dark_login(self):
        response = self.client.get("/dark/cockpit/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/dark/compte/"))

    def test_admin_stays_light_and_dark_admin_rejects_clients(self):
        self.client.force_login(self.client_user)
        self.assertEqual(self.client.get("/admin-backoffice/").status_code, 403)
        self.assertEqual(self.client.get("/dark/admin-backoffice/").status_code, 403)

        self.client.force_login(self.staff)
        light = self.client.get("/admin-backoffice/")
        self.assertEqual(light.status_code, 200)
        self.assertContains(light, "img/logo-96.png")
        self.assertContains(light, "Vue d'ensemble")
        self.assertNotContains(light, "dark-app.css")
        self.assertNotContains(light, 'data-theme="dark"')

        dark = self.client.get("/dark/admin-backoffice/")
        self.assertEqual(dark.status_code, 200)
        self.assertContains(dark, "dark-app.css")
        self.assertContains(dark, 'data-theme="dark"')
        self.assertContains(dark, "img/dark/mark.png")
        self.assertContains(dark, "img/dark/wordmark.png")
        self.assertContains(dark, 'href="/dark/admin-backoffice/users/"')
        self.assertContains(dark, 'href="/dark/admin-backoffice/facturation/"')
        self.assertContains(dark, "Vue d'ensemble")
        self.assertNotContains(dark, "img/logo-96.png")

        emails = self.client.get("/dark/admin-backoffice/emails/")
        self.assertEqual(emails.status_code, 200)
        self.assertContains(emails, "Emails automatiques")
        self.assertContains(emails, "dark-app.css")
        settings_page = self.client.get("/dark/admin-backoffice/settings/")
        self.assertEqual(settings_page.status_code, 200)
        self.assertContains(settings_page, "Coordonnées de contact")
