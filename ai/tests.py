from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounting.models import JournalEntry
from accounting.services import generate_portal
from companies.models import Company

from .assistant import execute_tool


class VoiceAssistantTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("artisan@example.com")
        self.other = User.objects.create_user("autre@example.com")
        self.company = Company.objects.create(
            owner=self.user,
            siren="812345678",
            denomination="Menuiserie Dupont",
            forme="SARL",
            regime="reel_simple",
            tva="reel",
            exercice_debut=date(2026, 1, 1),
            activites=["menuiserie"],
        )
        generate_portal(self.company)

    def test_unbalanced_entry_is_refused(self):
        result = execute_tool(self.user, self.company, "propose_entry", {
            "journal": "ACH",
            "label": "Perceuse",
            "lines": [
                {"account_code": "626", "debit": "100.00", "credit": "0"},
                {"account_code": "401", "debit": "0", "credit": "90.00"},
            ],
        })
        self.assertIn("error", result)

    def test_draft_invoice_is_a_draft(self):
        result = execute_tool(self.user, self.company, "draft_invoice", {
            "client_name": "Atelier Martin",
            "amount_ht": "800",
            "vat_rate": "20",
            "designation": "Pose de fenêtres",
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["invoice"]["amount_ttc"], "960.00")
        self.assertEqual(result["status"], "brouillon")
        self.assertIn("/factures/", result["invoice"]["url"])
        self.assertEqual(JournalEntry.objects.count(), 0)

    def test_draft_then_confirm(self):
        result = execute_tool(self.user, self.company, "propose_entry", {
            "journal": "ACH",
            "date": "2026-11-03",
            "label": "Perceuse Leroy Merlin",
            "lines": [
                {"account_code": "626", "debit": "100.00", "credit": "0"},
                {"account_code": "401", "debit": "0", "credit": "100.00"},
            ],
        })
        entry_id = result["entry"]["id"]
        entry = JournalEntry.objects.get(pk=entry_id)
        self.assertFalse(entry.validated)
        self.assertTrue(entry.drafted_by_ai)

        refused = execute_tool(self.user, self.company, "confirm_entry", {
            "entry_id": entry_id,
            "confirmation": "non",
        })
        self.assertIn("error", refused)
        entry.refresh_from_db()
        self.assertFalse(entry.validated)

        confirmed = execute_tool(self.user, self.company, "confirm_entry", {
            "entry_id": entry_id,
            "confirmation": "oui",
        })
        self.assertTrue(confirmed["ok"])
        entry.refresh_from_db()
        self.assertTrue(entry.validated)
        self.assertEqual(entry.lines.get(account__code="626").debit, Decimal("100.00"))

    def test_other_user_cannot_switch(self):
        with self.assertRaises(PermissionError):
            execute_tool(self.other, None, "switch_company", {"company_id": str(self.company.id)})

    def test_balance_ignores_drafts(self):
        execute_tool(self.user, self.company, "propose_entry", {
            "journal": "BQ",
            "label": "Apport",
            "lines": [
                {"account_code": "512", "debit": "50.00", "credit": "0"},
                {"account_code": "101", "debit": "0", "credit": "50.00"},
            ],
        })
        balance = execute_tool(self.user, self.company, "get_balance", {})
        self.assertEqual(balance["rows"], [])


class ClientDraftTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("clientdraft@example.com")
        self.company = Company.objects.create(
            owner=self.user,
            siren="121212121",
            denomination="IA Client Co",
            forme="SARL",
            regime="reel_simple",
            tva="reel",
            exercice_debut=date(2026, 1, 1),
        )
        generate_portal(self.company)
        self.http = self.client
        self.http.force_login(self.user)

    def test_draft_client_does_not_create_client(self):
        from documents.models import Client
        from .models import AiDraftEntry

        result = execute_tool(self.user, self.company, "draft_client", {
            "name": "Nouveau Client SA",
            "siren": "123456782",
            "email": "contact@nouveau.fr",
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "brouillon")
        self.assertEqual(Client.objects.filter(company=self.company).count(), 0)
        draft = AiDraftEntry.objects.get(pk=result["draft"]["id"])
        self.assertEqual(draft.kind, "client")
        self.assertEqual(draft.status, "pending")
        self.assertEqual(draft.proposed_data["name"], "Nouveau Client SA")

    def test_approve_creates_client_reject_does_not(self):
        from documents.models import Client
        from .models import AiDraftEntry

        result = execute_tool(self.user, self.company, "draft_client", {
            "name": "À Valider SARL",
            "siren": "987654321",
        })
        draft_id = result["draft"]["id"]
        # reject path
        other = execute_tool(self.user, self.company, "draft_client", {
            "name": "À Rejeter",
        })
        reject_id = other["draft"]["id"]
        resp = self.http.post(f"/agent/brouillons/{reject_id}/rejeter/")
        self.assertEqual(resp.status_code, 302)
        rejected = AiDraftEntry.objects.get(pk=reject_id)
        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(Client.objects.filter(company=self.company).count(), 0)

        resp = self.http.post(f"/agent/brouillons/{draft_id}/valider/")
        self.assertEqual(resp.status_code, 302)
        draft = AiDraftEntry.objects.get(pk=draft_id)
        self.assertEqual(draft.status, "validated")
        self.assertIsNotNone(draft.created_client_id)
        client = Client.objects.get(pk=draft.created_client_id)
        self.assertEqual(client.name, "À Valider SARL")
        self.assertEqual(client.siren, "987654321")




class ChatAminiaTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("chat@example.com", password="x")
        self.other = User.objects.create_user("chat-other@example.com", password="x")
        self.company = Company.objects.create(
            owner=self.user,
            siren="823456789",
            denomination="Atelier Chat",
            forme="SARL",
            regime="reel_simple",
            tva="reel",
            exercice_debut=date(2026, 1, 1),
            activites=["menuiserie"],
        )
        generate_portal(self.company)

    def test_chat_requires_login(self):
        r = self.client.post("/agent/chat/message/", {"message": "Bonjour"}, content_type="application/json")
        self.assertEqual(r.status_code, 302)

    def test_chat_empty_message(self):
        self.client.force_login(self.user)
        r = self.client.post(
            "/agent/chat/message/",
            data='{"message": "  "}',
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()["ok"])

    def test_chat_fallback_without_llm(self):
        from django.test import override_settings
        self.client.force_login(self.user)
        with override_settings(LLM_BASE_URL=""):
            r = self.client.post(
                "/agent/chat/message/",
                data='{"message": "Bonjour Aminia"}',
                content_type="application/json",
            )
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["fallback"])
        self.assertIn("disponible", payload["reply"].lower())
        from .models import Conversation, Message
        conv = Conversation.objects.get(pk=payload["conversation_id"])
        self.assertEqual(conv.user_id, self.user.id)
        self.assertEqual(conv.company_id, self.company.id)
        roles = list(conv.messages.order_by("created_at").values_list("role", flat=True))
        self.assertEqual(roles, ["user", "assistant"])

    def test_chat_tenant_isolation_on_conversation(self):
        from .models import Conversation
        self.client.force_login(self.user)
        from django.test import override_settings
        with override_settings(LLM_BASE_URL=""):
            r = self.client.post(
                "/agent/chat/message/",
                data='{"message": "Premier"}',
                content_type="application/json",
            )
        cid = r.json()["conversation_id"]
        self.client.force_login(self.other)
        other_co = Company.objects.create(
            owner=self.other,
            siren="899999999",
            denomination="Autre",
            forme="SAS",
            regime="reel_simple",
            tva="reel",
            exercice_debut=date(2026, 1, 1),
            activites=["plomberie"],
        )
        generate_portal(other_co)
        with override_settings(LLM_BASE_URL=""):
            r2 = self.client.post(
                "/agent/chat/message/",
                data=f'{{"message": "Intrus", "conversation_id": "{cid}"}}',
                content_type="application/json",
            )
        self.assertEqual(r2.status_code, 404)

    def test_chat_page_ok(self):
        self.client.force_login(self.user)
        r = self.client.get("/agent/chat/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Aminia")



class AminiaChooserMarkupTests(TestCase):
    """Le FAB Aminia expose le sélecteur Vocal|Chat sur les pages cockpit."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("chooser@example.com", password="x")
        self.company = Company.objects.create(
            owner=self.user,
            siren="845678901",
            denomination="Chooser SARL",
            forme="SARL",
            regime="reel_simple",
            tva="reel",
            exercice_debut=date(2026, 1, 1),
            activites=["menuiserie"],
        )
        generate_portal(self.company)

    def test_cockpit_contains_chooser_and_chat_panel(self):
        self.client.force_login(self.user)
        r = self.client.get(f"/cockpit/?societe={self.company.id}")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'data-agent-open')
        self.assertContains(r, 'data-agent-chooser')
        self.assertContains(r, 'data-agent-pick="voice"')
        self.assertContains(r, 'data-agent-pick="chat"')
        self.assertContains(r, 'data-agent-chat')
        self.assertContains(r, 'data-agent-chat-form')
        self.assertContains(r, "app.css?v=2026.11.05.13")  # cache-bust static
        self.assertContains(r, "app.js?v=2026.11.05.13")

    def test_chat_endpoint_still_reachable(self):
        self.client.force_login(self.user)
        from django.test import override_settings
        with override_settings(LLM_BASE_URL=""):
            r = self.client.post(
                "/agent/chat/message/",
                data='{"message": "Salut"}',
                content_type="application/json",
            )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])


class PlanPromptRuntimeTests(TestCase):
    """Le chat et la voix envoient la consigne générale plus celle du forfait."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("forfait@example.com")
        self.company = Company.objects.create(
            owner=self.user,
            siren="812345678",
            denomination="Menuiserie Dupont",
            forme="SARL",
            regime="micro",
            tva="franchise",
            exercice_debut=date(2026, 1, 1),
        )
        from billing.models import Plan, Subscription

        self.micro = Plan.objects.create(code="micro", name="Micro", price_eur=29)
        self.pro = Plan.objects.create(code="pro", name="Pro", price_eur=79)
        self.subscription = Subscription.objects.create(user=self.user, plan=self.micro, status="active")

    def test_chat_system_prompt_uses_global_and_plan(self):
        from django.test import override_settings

        from admin_backoffice.models import SiteConfiguration

        SiteConfiguration.objects.create(ai_system_prompt="CONSIGNE-GLOBALE-TEST")
        self.micro.ai_prompt = "CONSIGNE-MICRO-TEST ne révèle pas les fonctions d'un forfait supérieur"
        self.micro.save(update_fields=["ai_prompt"])

        class Fake:
            def chat(self, messages, tools=None):
                self.messages = messages
                self.tools = tools
                return {"choices": [{"message": {"content": "Bien reçu.", "tool_calls": []}}]}

        fake = Fake()
        from ai.chat import get_or_create_conversation, run_chat_turn

        conversation = get_or_create_conversation(self.user, self.company)
        with override_settings(LLM_BASE_URL="http://llm.test/v1"):
            result = run_chat_turn(self.user, self.company, conversation, "Bonjour", client=fake)
        self.assertTrue(result["ok"])
        self.assertFalse(result["fallback"])
        system = fake.messages[0]["content"]
        self.assertEqual(fake.messages[0]["role"], "system")
        self.assertIn("CONSIGNE-GLOBALE-TEST", system)
        self.assertIn("CONSIGNE-MICRO-TEST", system)
        self.assertTrue(system.rindex("CONSIGNE-MICRO-TEST") > system.index("CONSIGNE-GLOBALE-TEST"))
        names = [tool["function"]["name"] for tool in fake.tools]
        self.assertNotIn("draft_invoice", names)
        self.assertIn("get_balance", names)

    def test_micro_plan_blocks_invoice_tool(self):
        result = execute_tool(self.user, self.company, "draft_invoice", {
            "client_name": "Atelier",
            "amount_ht": "10",
        })
        self.assertIn("error", result)
        self.assertIn("forfait", result["error"])

    def test_pro_plan_keeps_invoice_tool(self):
        self.subscription.plan = self.pro
        self.subscription.save(update_fields=["plan"])
        from ai.prompts import agent_instructions

        text = agent_instructions(self.user, self.company, channel="voice")
        self.assertIn("l'ensemble des fonctions du produit", text)
        result = execute_tool(self.user, self.company, "draft_invoice", {
            "client_name": "Atelier Martin",
            "amount_ht": "800",
            "vat_rate": "20",
            "designation": "Pose",
        })
        self.assertTrue(result["ok"])

    def test_voice_session_includes_plan_prompt(self):
        from unittest import mock

        self.client.force_login(self.user)
        with mock.patch("ai.views._mint_secret", return_value=({"token": "ephemeral", "expires_at": None}, None)):
            response = self.client.post("/agent/session/", data="{}", content_type="application/json")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("Forfait d'entrée", payload["instructions"])
        self.assertIn("Cadre du forfait", payload["instructions"])
        names = [tool["name"] for tool in payload["tools"]]
        self.assertNotIn("draft_invoice", names)
        self.assertNotIn("draft_client", names)
