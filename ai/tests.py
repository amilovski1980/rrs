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
