from django.contrib.auth import get_user_model
from django.test import TestCase

from core.demo import DEMO_EMAIL


class EmailLoginTests(TestCase):
    def test_new_email_opens_its_cockpit(self):
        response = self.client.post("/compte/", {"email": "artisan@exemple.fr"})
        self.assertRedirects(response, "/cockpit/", fetch_redirect_response=False)
        self.assertTrue(get_user_model().objects.filter(email="artisan@exemple.fr").exists())
        cockpit = self.client.get("/cockpit/")
        self.assertEqual(cockpit.status_code, 200)
        self.assertContains(cockpit, "artisan@exemple.fr")

    def test_same_email_reopens_the_same_account(self):
        self.client.post("/compte/", {"email": "artisan@exemple.fr"})
        self.client.post("/compte/logout/")
        again = self.client.post("/compte/", {"email": "Artisan@exemple.fr"})
        self.assertRedirects(again, "/cockpit/", fetch_redirect_response=False)
        self.assertEqual(get_user_model().objects.filter(email__iexact="artisan@exemple.fr").count(), 1)

    def test_demo_email_opens_the_seeded_company(self):
        response = self.client.post("/compte/", {"email": DEMO_EMAIL}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Menuiserie Dupont")
