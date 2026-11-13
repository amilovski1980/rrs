from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from companies.models import Company


def _company(owner):
    return Company.objects.create(
        owner=owner,
        siren="812345679",
        denomination="Atelier Signature",
        forme="SARL",
        phone="01 23 45 67 89",
        email="contact@atelier.fr",
        regime="reel_simple",
        tva="reel",
        exercice_debut=date(2026, 1, 1),
    )


class ProfileSignatureTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "camille@example.fr", password="password123"
        )
        self.company = _company(self.user)
        self.http = self.client
        self.http.force_login(self.user)

    def test_profile_saves_identity_and_custom_signature(self):
        response = self.http.post(reverse("profile"), {
            "action": "profile",
            "first_name": "Camille",
            "last_name": "Martin",
            "job_title": "Dirigeante",
            "email_signature": "Camille Martin\nAtelier Signature\n06 12 34 56 78",
        })
        self.assertRedirects(response, reverse("profile"), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Camille")
        self.assertEqual(self.user.last_name, "Martin")
        self.assertEqual(self.user.job_title, "Dirigeante")
        self.assertEqual(
            self.user.signature_text(self.company),
            "Camille Martin\nAtelier Signature\n06 12 34 56 78",
        )
        page = self.http.get(reverse("profile"))
        self.assertContains(page, "Camille Martin")
        self.assertContains(page, "Signature email")
        self.assertContains(page, "Personnalisée")
        dark = self.http.get("/dark/compte/profil/")
        self.assertEqual(dark.status_code, 200)
        self.assertContains(dark, "Camille Martin")
        self.assertContains(dark, "dark-app.css")

    def test_auto_signature_uses_name_job_company_and_contacts(self):
        self.user.first_name = "Camille"
        self.user.last_name = "Martin"
        self.user.job_title = "Dirigeante"
        self.user.save(update_fields=["first_name", "last_name", "job_title"])
        signature = self.user.signature_text(self.company)
        self.assertIn("Camille Martin", signature)
        self.assertIn("Dirigeante", signature)
        self.assertIn("Atelier Signature", signature)
        self.assertIn("camille@example.fr", signature)
        self.assertIn("01 23 45 67 89", signature)
        page = self.http.get(reverse("profile"))
        self.assertContains(page, "Automatique")

    def test_signature_falls_back_to_email_local_part(self):
        user = get_user_model().objects.create_user("jean.dupont@example.fr")
        signature = user.signature_text()
        self.assertIn("Jean Dupont", signature)
        self.assertIn("jean.dupont@example.fr", signature)

    def test_password_form_still_works_with_action_field(self):
        response = self.http.post(reverse("profile"), {
            "action": "password",
            "current_password": "password123",
            "new_password1": "Nouveau-Mot-De-Passe-2026",
            "new_password2": "Nouveau-Mot-De-Passe-2026",
        })
        self.assertRedirects(response, reverse("profile"), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Nouveau-Mot-De-Passe-2026"))
