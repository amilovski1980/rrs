import json
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User


@override_settings(VOCALIA_API_TOKEN="test-secret")
class VoiceSignupTests(TestCase):
    def post_signup(self, payload, token="test-secret"):
        return self.client.post(
            reverse("vocalia_voice_signup"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    def test_requires_authentication(self):
        response = self.post_signup({"email": "a@example.com", "consent": True}, "wrong")
        self.assertEqual(response.status_code, 401)

    def test_requires_explicit_consent(self):
        response = self.post_signup({"email": "a@example.com", "consent": False})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(email="a@example.com").exists())

    def test_rejects_invalid_email(self):
        response = self.post_signup({"email": "not-an-email", "consent": True})
        self.assertEqual(response.status_code, 400)

    @patch("accounts.voice_signup.send_template_email")
    def test_creates_email_only_user_and_sends_link(self, send):
        response = self.post_signup({"email": "new@example.com", "consent": True})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {"status": "email_sent"})
        self.assertTrue(User.objects.filter(email="new@example.com").exists())
        self.assertFalse(User.objects.get(email="new@example.com").has_usable_password())
        send.assert_called_once()

    @patch("accounts.voice_signup.send_template_email")
    def test_existing_user_is_not_duplicated(self, send):
        User.objects.create_user("existing@example.com")
        response = self.post_signup({"email": "existing@example.com", "consent": True})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(User.objects.filter(email="existing@example.com").count(), 1)
        send.assert_called_once()
