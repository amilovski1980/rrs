from datetime import date
from decimal import Decimal
from unittest import mock

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
            "designation": "Pose de fenÃªtres",
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
            "name": "Ã€ Valider SARL",
            "siren": "987654321",
        })
        draft_id = result["draft"]["id"]
        # reject path
        other = execute_tool(self.user, self.company, "draft_client", {
            "name": "Ã€ Rejeter",
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
        self.assertEqual(client.name, "Ã€ Valider SARL")
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
    """Le FAB Aminia expose le sÃ©lecteur Vocal|Chat sur les pages cockpit."""

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
        self.assertRegex(r.content.decode(), r"app\.css\?v=\d{4}\.\d{2}\.\d{2}\.\d+")  # cache-bust static
        self.assertRegex(r.content.decode(), r"app\.js\?v=\d{4}\.\d{2}\.\d{2}\.\d+")

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
    """Le chat et la voix envoient la consigne gÃ©nÃ©rale plus celle du forfait."""

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
        self.micro.ai_prompt = "CONSIGNE-MICRO-TEST ne rÃ©vÃ¨le pas les fonctions d'un forfait supÃ©rieur"
        self.micro.save(update_fields=["ai_prompt"])

        class Fake:
            def chat(self, messages, tools=None):
                self.messages = messages
                self.tools = tools
                return {"choices": [{"message": {"content": "Bien reÃ§u.", "tool_calls": []}}]}

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
        self.assertIn("Tu gÃ¨res la comptabilitÃ© de la sociÃ©tÃ©", system)
        self.assertNotIn("Contexte administrateur", system)
        self.assertTrue(system.rindex("CONSIGNE-MICRO-TEST") > system.index("CONSIGNE-GLOBALE-TEST"))
        names = [tool["function"]["name"] for tool in fake.tools]
        self.assertNotIn("draft_invoice", names)
        self.assertIn("get_balance", names)

    def test_staff_chat_uses_admin_prompt_and_all_tools(self):
        from django.test import override_settings

        from admin_backoffice.models import SiteConfiguration

        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        SiteConfiguration.objects.create(admin_ai_prompt="CONSIGNE-ADMIN-TEST corrige le site")

        class Fake:
            def chat(self, messages, tools=None):
                self.messages = messages
                self.tools = tools
                return {"choices": [{"message": {"content": "Bien reÃ§u.", "tool_calls": []}}]}

        fake = Fake()
        from ai.chat import get_or_create_conversation, run_chat_turn

        conversation = get_or_create_conversation(self.user, self.company)
        with override_settings(LLM_BASE_URL="http://llm.test/v1"):
            result = run_chat_turn(self.user, self.company, conversation, "Corrige le site", client=fake)
        self.assertTrue(result["ok"])
        system = fake.messages[0]["content"]
        self.assertIn("CONSIGNE-ADMIN-TEST", system)
        self.assertIn("Cadre administrateur", system)
        self.assertIn("Contexte administrateur", system)
        self.assertIn("sociÃ©tÃ© de test", system)
        self.assertNotIn("Tu gÃ¨res la comptabilitÃ© de la sociÃ©tÃ©", system)
        names = [tool["function"]["name"] for tool in fake.tools]
        self.assertIn("draft_invoice", names)

    def test_staff_without_company_keeps_admin_context(self):
        from ai.prompts import agent_instructions

        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        text = agent_instructions(self.user, None, channel="voice")
        self.assertIn("Contexte administrateur", text)
        self.assertIn("aucune sociÃ©tÃ© n'est sÃ©lectionnÃ©e", text)
        self.assertNotIn("ajouter un SIREN", text)
        self.assertNotIn("Tu gÃ¨res la comptabilitÃ©", text)

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
        locked = self.client.post("/agent/session/", data="{}", content_type="application/json")
        self.assertEqual(locked.status_code, 403)
        self.assertIn("forfait", locked.json()["message"].lower())

        self.subscription.plan = self.pro
        self.subscription.save(update_fields=["plan"])
        with mock.patch("ai.views._mint_secret", return_value=({"token": "ephemeral", "expires_at": None}, None)):
            response = self.client.post("/agent/session/", data="{}", content_type="application/json")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("l'ensemble des fonctions du produit", payload["instructions"])
        names = [tool["name"] for tool in payload["tools"]]
        self.assertIn("draft_invoice", names)


SAMPLE_CARD = {
    "siren": "812345678",
    "siret": "81234567800019",
    "denomination": "BTP Martin",
    "forme": "SARL",
    "adresse": "12 rue des MaÃ§ons 69003 LYON",
    "code_naf": "4322B",
    "naf": "43.22B",
    "etat": "Active",
}


class CompanySearchToolTests(TestCase):
    """Outils Aminia : recherche annuaire officiel + sÃ©lection par numÃ©ro."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("artisan@example.com")
        self.company = Company.objects.create(
            owner=self.user,
            siren="552100554",
            denomination="Menuiserie Dupont",
            forme="SARL",
            regime="reel_simple",
            tva="reel",
            exercice_debut=date(2026, 1, 1),
            activites=["menuiserie"],
        )
        generate_portal(self.company)

    def test_search_numbers_results_and_memorizes_session(self):
        results = [{**SAMPLE_CARD, "index": 1}, {**SAMPLE_CARD, "index": 2}]
        memory = {}
        with mock.patch("integrations.insee.search_french_companies") as fake:
            fake.return_value = (results, None, 0, True)
            result = execute_tool(self.user, self.company, "search_french_companies", {
                "query": "BTP Martin", "city": "Lyon",
            }, session=memory)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["results"][0]["index"], 1)
        self.assertEqual(result["results"][1]["index"], 2)
        self.assertIn("1", memory.get("aminia_results", {}))
        self.assertEqual(memory["aminia_results"]["1"]["siren"], "812345678")

    def test_search_rate_limit_is_speakable(self):
        with mock.patch("integrations.insee.search_french_companies") as fake:
            fake.return_value = ([], "rate_limit", 45, False)
            result = execute_tool(self.user, self.company, "search_french_companies", {
                "query": "Martin",
            }, session={})
        self.assertIn("error", result)
        self.assertEqual(result["retry_after_seconds"], 45)

    def test_search_empty_is_not_a_proof_of_nonexistence(self):
        with mock.patch("integrations.insee.search_french_companies") as fake:
            fake.return_value = ([], None, 0, False)
            result = execute_tool(self.user, self.company, "search_french_companies", {
                "query": "Inconnue Totale",
            }, session={})
        self.assertEqual(result["results"], [])
        self.assertIn("ne prouve pas", result["message"])

    def test_choose_by_index_flags_existing_client(self):
        from documents.models import Client

        Client.objects.create(company=self.company, name="BTP Martin", siren="812345678")
        session = {"aminia_results": {"1": {"siren": "812345678", "siret": "81234567800019"}}}
        with mock.patch("integrations.insee.official_card") as card:
            card.return_value = (dict(SAMPLE_CARD), None)
            result = execute_tool(self.user, self.company, "choose_company_result", {
                "index": 1,
            }, session=session)
        self.assertEqual(result["selected"]["siren"], "812345678")
        self.assertTrue(result["selected"]["deja_client"])
        self.assertFalse(result["selected"]["deja_fournisseur"])
        self.assertIn("aminia_picked", session)

    def test_choose_by_siren_without_search_memory(self):
        with mock.patch("integrations.insee.official_card") as card:
            card.return_value = (dict(SAMPLE_CARD), None)
            result = execute_tool(self.user, self.company, "choose_company_result", {
                "siren": "812345678",
            }, session={})
        self.assertTrue(result["selected"]["deja_client"] is False)
        self.assertEqual(result["selected"]["denomination"], "BTP Martin")

    def test_choose_rejects_bad_siren(self):
        result = execute_tool(self.user, self.company, "choose_company_result", {
            "siren": "123", "index": 1,
        }, session={})
        self.assertIn("error", result)


    def test_choose_from_panel_via_get(self):
        """Le clic Â« Choisir cette entreprise Â» du panneau (mode dÃ©mo inclus)."""
        self.client.force_login(self.user)
        with mock.patch("integrations.insee.search_french_companies") as fake:
            fake.return_value = ([{**SAMPLE_CARD, "index": 1}], None, 0, False)
            self.client.get("/agent/recherche/", {"query": "BTP Martin"})
        with mock.patch("integrations.insee.official_card") as card:
            card.return_value = (dict(SAMPLE_CARD), None)
            response = self.client.get("/agent/recherche/", {"choisir": "1"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["selected"]["siren"], "812345678")
        self.assertIn("aminia_picked", self.client.session)


class CompanySearchEndpointTests(TestCase):
    """Endpoint JSON /agent/recherche/ pour les Ã©crans de saisie."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("artisan@example.com")
        self.company = Company.objects.create(
            owner=self.user,
            siren="812345679",
            denomination="Menuiserie Dupont",
            forme="SARL",
            regime="reel_simple",
            tva="reel",
            exercice_debut=date(2026, 1, 1),
        )
        generate_portal(self.company)

    def test_requires_authentication(self):
        response = self.client.get("/agent/recherche/", {"query": "BTP"})
        self.assertEqual(response.status_code, 401)

    def test_requires_query(self):
        self.client.force_login(self.user)
        response = self.client.get("/agent/recherche/")
        self.assertEqual(response.status_code, 400)

    def test_returns_numbered_results(self):
        self.client.force_login(self.user)
        with mock.patch("integrations.insee.search_french_companies") as fake:
            fake.return_value = ([{**SAMPLE_CARD, "index": 1}], None, 0, False)
            response = self.client.get("/agent/recherche/", {"query": "BTP Martin"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["denomination"], "BTP Martin")

class TextProviderOllamaTests(TestCase):
    """Le chat Aminia peut utiliser un serveur Ollama local."""

    def test_ollama_choice_is_available(self):
        from admin_backoffice.models import SiteConfiguration

        choices = SiteConfiguration._meta.get_field("ai_text_provider").choices
        self.assertIn(("ollama", "Ollama (local)"), choices)

    def test_db_choice_and_fields_win(self):
        from admin_backoffice.models import SiteConfiguration
        from django.test import override_settings

        from .providers import text_provider

        SiteConfiguration.objects.update_or_create(
            id=1,
            defaults={
                "ai_text_provider": "ollama",
                "llm_base_url": "http://gpu.local:11434/v1",
                "llm_model": "llama3.1:8b",
                "llm_api_key": "",
            },
        )
        with override_settings(OLLAMA_BASE_URL="", LLM_MODEL="autre", LLM_API_KEY="cle-env"):
            spec = text_provider()
        self.assertEqual(spec["code"], "ollama")
        self.assertEqual(spec["base"], "http://gpu.local:11434/v1")
        self.assertEqual(spec["model"], "llama3.1:8b")
        self.assertTrue(spec["configured"])

    def test_default_ollama_base_without_model(self):
        from admin_backoffice.models import SiteConfiguration
        from django.test import override_settings

        from .providers import OLLAMA_DEFAULT_BASE, text_provider

        SiteConfiguration.objects.update_or_create(
            id=1, defaults={"ai_text_provider": "ollama", "llm_base_url": "", "llm_model": ""}
        )
        with override_settings(OLLAMA_BASE_URL="", LLM_MODEL=""):
            spec = text_provider()
        self.assertEqual(spec["base"], OLLAMA_DEFAULT_BASE)
        self.assertFalse(spec["configured"])

class ListAiModelsTests(TestCase):
    """La liste des modÃ¨les passe par /models puis /api/tags (Ollama)."""

    @staticmethod
    def _patch_handler(handler):
        import httpx
        from unittest.mock import patch

        original_client = httpx.Client

        def factory(**kwargs):
            kwargs.pop("transport", None)
            return original_client(transport=httpx.MockTransport(handler), **kwargs)

        return patch.object(httpx, "Client", new=factory)

    def test_openai_models(self):
        from .providers import list_ai_models

        def handler(request):
            self.assertEqual(request.method, "GET")
            import httpx

            return httpx.Response(200, json={"data": [{"id": "qwen2.5:7b"}, {"id": "mistral-7b"}]})

        with self._patch_handler(handler):
            result = list_ai_models("http://gpu.local:8000/v1", "cle")
        self.assertEqual(result["source"], "openai")
        self.assertEqual(result["models"], ["mistral-7b", "qwen2.5:7b"])

    def test_ollama_tags_fallback(self):
        import httpx

        from .providers import list_ai_models

        def handler(request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(str(request.url), "http://gpu.local:11434/api/tags")
            return httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}]})

        with self._patch_handler(handler):
            result = list_ai_models("http://gpu.local:11434/v1")
        self.assertEqual(result["source"], "ollama")
        self.assertEqual(result["models"], ["llama3.1:8b"])

    def test_unreachable_base_raises(self):
        import httpx

        from .providers import list_ai_models

        calls = {"count": 0}

        def handler(request):
            calls["count"] += 1
            return httpx.Response(404)

        with self._patch_handler(handler):
            with self.assertRaises(ValueError):
                list_ai_models("http://nowhere.local:9999/v1")
        self.assertEqual(calls["count"], 2)

    def test_refuses_non_http(self):
        from .providers import list_ai_models

        with self.assertRaises(ValueError):
            list_ai_models("file:///etc")
