"""Règles d'accueil Aminia (mémoire 24 h) et session vocale."""
import datetime
from datetime import timedelta

from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch

from ai.models import GreetingStamp
from admin_backoffice.models import SiteConfiguration
from companies.models import Company

User = get_user_model()


class GreetingRuleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("bonjour@example.com")

    def test_first_call_says_bonjour_and_sets_stamp(self):
        response = self._session()
        self.assertIn("Bonjour", response["greeting"])
        stamp = GreetingStamp.objects.get(user=self.user)
        self.assertTrue(timezone.now() - stamp.last_greeted_at < timedelta(minutes=5))

    def test_quick_second_call_says_oui(self):
        stamp = GreetingStamp.objects.create(user=self.user)
        GreetingStamp.objects.filter(pk=stamp.pk).update(
            last_greeted_at=timezone.now() - timedelta(hours=2)
        )
        response = self._session()
        self.assertIn("Oui", response["greeting"])
        # L'horodatage n'est PAS réinitialisé pendant la fenêtre de 24 h.
        stamp = GreetingStamp.objects.get(user=self.user)
        elapsed = timezone.now() - stamp.last_greeted_at
        self.assertGreater(elapsed, timedelta(hours=1, minutes=30))
        self.assertLess(elapsed, timedelta(hours=3))

    def test_call_after_24h_says_bonjour_again(self):
        stamp = GreetingStamp.objects.create(user=self.user)
        # auto_now=True écrase la valeur : on l'impose par update() brut.
        GreetingStamp.objects.filter(pk=stamp.pk).update(
            last_greeted_at=timezone.now() - timedelta(hours=30)
        )
        response = self._session()
        self.assertIn("Bonjour", response["greeting"])
        stamp = GreetingStamp.objects.get(user=self.user)
        self.assertTrue(timezone.now() - stamp.last_greeted_at < timedelta(minutes=5))

    def test_refresh_does_not_resay_bonjour(self):
        self._session()
        self._session()
        response = self._session()
        self.assertIn("Oui", response["greeting"])

    def _session(self):
        self.client.force_login(self.user)
        with patch("ai.views._mint_secret") as mint:
            mint.return_value = ({"token": "tok", "expires_at": None}, None)
            response = self.client.post(reverse("voice_session"), {})
        self.assertEqual(response.status_code, 200)
        return response.json()


class SessionFallbackTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("fallback@example.com")
        self.company = Company.objects.create(
            owner=self.user,
            siren="811223344",
            denomination="Accueil SARL",
            forme="SARL",
            regime="reel_simple",
            tva="reel",
            exercice_debut=datetime.date(2026, 1, 1),
        )
        self.company.company = self.company
        from accounting.services import generate_portal

        generate_portal(self.company)

    def test_elevenlabs_selected_without_key_falls_back_to_xai(self):
        from django.test import override_settings

        SiteConfiguration.objects.update_or_create(
            id=1,
            defaults={"voice_call_provider": "elevenlabs", "xai_api_key": "xai"},
        )
        with override_settings(ELEVENLABS_API_KEY=""):
            with patch("ai.views._mint_secret") as mint:
                mint.return_value = ({"token": "tok", "expires_at": None}, None)
                self.client.force_login(self.user)
                response = self.client.post(reverse("voice_session"), {})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["provider"], "xai")
        self.assertIn("ElevenLabs", data.get("notice", ""))
        self.assertIn("Bonjour", data["greeting"])

    def test_lock_api_is_served_by_shell(self):
        from pathlib import Path

        self.client.force_login(self.user)
        response = self.client.get(reverse("cockpit"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("voice-shell.js", content)
        self.assertIn("data-agent-log", content)
        shell_js = (
            Path(__file__).resolve().parent.parent / "static" / "js" / "voice-shell.js"
        ).read_text(encoding="utf-8")
        self.assertIn("setLock", shell_js)
        self.assertIn("aminia-locked", shell_js)
        # Garde-fou : le cockpit reste utilisable normalement sans Aminia.
        self.assertIn("m-footer", content)


class SilenceWatchdogTests(SimpleTestCase):
    """Raccrochage automatique : 4 s puis 5 s, annulé au retour de parole."""

    def test_timers_present_in_voice_engine(self):
        script = (
            Path(__file__).resolve().parent.parent / "static" / "js" / "grok-voice.js"
        ).read_text(encoding="utf-8")
        self.assertIn("armSilence", script)
        self.assertIn('setStatus("Vous êtes toujours là ?")', script)
        self.assertIn('setStatus("Je vous laisse, à bientôt.")', script)
        self.assertIn("4000", script)
        self.assertIn("5000", script)
        self.assertIn("clearSilence", script)
