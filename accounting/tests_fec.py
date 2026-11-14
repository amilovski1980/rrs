from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from companies.models import Company

from .fec import FEC_COLUMNS, build_fec
from .models import EntryLine, Journal, JournalEntry
from .services import generate_portal


class FecExportTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(email="fec@example.fr", password="secret")
        self.company = Company.objects.create(
            owner=self.user,
            siren="666777888",
            denomination="Atelier FEC",
            regime="reel_simple",
            tva="reel",
        )
        generate_portal(self.company)
        self.journal = Journal.objects.get(company=self.company, code="ACH")

    def _entry(self, validated=True, label="Achat test"):
        entry = JournalEntry.objects.create(
            company=self.company,
            journal=self.journal,
            date=date(2026, 4, 15),
            label=label,
            reference="FEC-001",
            validated=validated,
        )
        EntryLine.objects.create(
            entry=entry, account=self.company.accounts.get(code="611"), debit=Decimal("100.00"), credit=Decimal("0.00")
        )
        EntryLine.objects.create(
            entry=entry, account=self.company.accounts.get(code="401"), debit=Decimal("0.00"), credit=Decimal("100.00")
        )
        return entry

    def test_header_and_validated_lines(self):
        self._entry()
        payload = build_fec(self.company, date(2026, 1, 1), date(2026, 12, 31))
        lines = payload.splitlines()
        self.assertEqual(lines[0].split("\t"), FEC_COLUMNS)
        body = payload.splitlines()[1:]
        self.assertEqual(len(body), 2)
        self.assertIn("100,00", payload)
        self.assertIn("Achat test", payload)
        self.assertIn("ACH", payload)

    def test_draft_entries_are_excluded(self):
        self._entry(validated=False, label="Brouillon exclu")
        payload = build_fec(self.company, date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual(len(payload.splitlines()), 1)
        self.assertNotIn("Brouillon exclu", payload)
