import re
from urllib.parse import urlparse

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from accounts.models import MagicLink

PASSWORD = "Cockpit-Lyonnais-2026"
NEW_PASSWORD = "Nouveau-Cockpit-2026"


def _user(email, password=None):
    return get_user_model().objects.create_user(email, password=password)


def _reset_path(body):
    match = re.search(r"https?://\S+", body)
    assert match, body
    return urlparse(match.group(0).rstrip(").,")).path


class PasswordAuthTests(TestCase):
    def test_signup_password_then_login_and_failure(self):
        user = _user("artisan@exemple.fr", password=PASSWORD)
        ok = self.client.post("/compte/", {"email": "Artisan@exemple.fr", "password": PASSWORD})
        self.assertRedirects(ok, "/cockpit/", fetch_redirect_response=False)
        self.client.post("/compte/logout/")
        bad = self.client.post("/compte/", {"email": "artisan@exemple.fr", "password": "mauvais-mot"})
        self.assertContains(bad, "Email ou mot de passe incorrect")
        self.assertFalse(user.__class__.objects.get(pk=user.pk).check_password("mauvais-mot"))

    def test_account_without_password_can_set_one_by_email(self):
        user = _user("ancien@exemple.fr")
        self.assertFalse(user.has_usable_password())
        blocked = self.client.post("/compte/", {"email": "ancien@exemple.fr", "password": PASSWORD})
        self.assertContains(blocked, "Email ou mot de passe incorrect")
        unknown = self.client.post(reverse("password_reset"), {"email": "personne@exemple.fr"})
        self.assertRedirects(unknown, reverse("password_reset_done"), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 0)
        sent = self.client.post(reverse("password_reset"), {"email": "Ancien@exemple.fr"})
        self.assertRedirects(sent, reverse("password_reset_done"), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn(PASSWORD, mail.outbox[0].body)
        self.assertIn("une heure", mail.outbox[0].body.lower())
        path = _reset_path(mail.outbox[0].body)
        opened = self.client.get(path)
        self.assertEqual(opened.status_code, 302)
        saved = self.client.post(opened.url, {
            "new_password1": PASSWORD,
            "new_password2": PASSWORD,
        })
        self.assertRedirects(saved, reverse("password_reset_complete"), fetch_redirect_response=False)
        user.refresh_from_db()
        self.assertTrue(user.check_password(PASSWORD))
        self.assertNotIn(PASSWORD, user.password)
        login = self.client.post("/compte/", {"email": "ancien@exemple.fr", "password": PASSWORD})
        self.assertRedirects(login, "/cockpit/", fetch_redirect_response=False)

    def test_logged_in_user_changes_password(self):
        user = _user("dirigeant@exemple.fr", password=PASSWORD)
        self.client.force_login(user)
        page = self.client.get(reverse("profile"))
        self.assertContains(page, "Mot de passe actuel")
        wrong = self.client.post(reverse("profile"), {
            "current_password": "pas-le-bon",
            "new_password1": NEW_PASSWORD,
            "new_password2": NEW_PASSWORD,
        })
        self.assertContains(wrong, "incorrect")
        user.refresh_from_db()
        self.assertTrue(user.check_password(PASSWORD))
        ok = self.client.post(reverse("profile"), {
            "current_password": PASSWORD,
            "new_password1": NEW_PASSWORD,
            "new_password2": NEW_PASSWORD,
        })
        self.assertRedirects(ok, reverse("profile"), fetch_redirect_response=False)
        user.refresh_from_db()
        self.assertTrue(user.check_password(NEW_PASSWORD))
        self.assertNotIn(NEW_PASSWORD, user.password)
        self.client.post("/compte/logout/")
        again = self.client.post("/compte/", {"email": user.email, "password": NEW_PASSWORD})
        self.assertRedirects(again, "/cockpit/", fetch_redirect_response=False)

    def test_magic_link_sets_password_without_locking_the_cockpit(self):
        user = _user("lien@exemple.fr")
        asked = self.client.post(reverse("magic_link_email"), {"email": "lien@exemple.fr"})
        self.assertRedirects(asked, reverse("magic_link_email_done"), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        hidden = self.client.post(reverse("magic_link_email"), {"email": "absent@exemple.fr"})
        self.assertRedirects(hidden, reverse("magic_link_email_done"), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        path = _reset_path(mail.outbox[0].body)
        opened = self.client.get(path)
        self.assertRedirects(opened, reverse("profile"), fetch_redirect_response=False)
        self.assertEqual(MagicLink.objects.filter(user=user, used_at__isnull=False).count(), 1)
        skipped = self.client.get("/cockpit/")
        self.assertEqual(skipped.status_code, 200)
        defined = self.client.post(reverse("profile"), {
            "new_password1": PASSWORD,
            "new_password2": PASSWORD,
        })
        self.assertRedirects(defined, reverse("profile"), fetch_redirect_response=False)
        user.refresh_from_db()
        self.assertTrue(user.check_password(PASSWORD))
        self.assertNotContains(self.client.get(reverse("profile")), PASSWORD)
