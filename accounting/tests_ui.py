from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from companies.models import Company

from .forms import EntryForm
from .models import EntryLine, Journal, JournalEntry
from .services import generate_portal


class EntryUiTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(email="ui@example.fr")
        self.company = Company.objects.create(
            owner=user,
            siren="777888999",
            denomination="Atelier UI",
            regime="reel_simple",
            tva="reel",
        )
        generate_portal(self.company)
        self.journal = Journal.objects.get(company=self.company, code="ACH")
        self.client.force_login(user)

    def test_entry_date_has_native_calendar_and_today_default(self):
        form = EntryForm(company=self.company)
        self.assertEqual(form.fields["date"].widget.input_type, "date")
        self.assertEqual(form.initial.get("date"), timezone.localdate())

    def test_draft_entry_can_be_validated(self):
        entry = JournalEntry.objects.create(
            company=self.company,
            journal=self.journal,
            date=date(2026, 11, 14),
            label="Brouillon à valider",
            validated=False,
        )
        accounts = list(self.company.accounts.order_by("code")[:2])
        EntryLine.objects.create(
            entry=entry,
            account=accounts[0],
            debit=Decimal("30.00"),
            credit=Decimal("0.00"),
        )
        EntryLine.objects.create(
            entry=entry,
            account=accounts[1],
            debit=Decimal("0.00"),
            credit=Decimal("30.00"),
        )
        response = self.client.post(
            reverse("entry_validate", args=[entry.id])
            + f"?societe={self.company.id}"
        )
        self.assertEqual(response.status_code, 302)
        entry.refresh_from_db()
        self.assertTrue(entry.validated)

    def test_unbalanced_draft_stays_in_drafts(self):
        entry = JournalEntry.objects.create(
            company=self.company,
            journal=self.journal,
            date=date(2026, 11, 14),
            label="Brouillon déséquilibré",
            validated=False,
        )
        EntryLine.objects.create(
            entry=entry,
            account=self.company.accounts.order_by("code").first(),
            debit=Decimal("30.00"),
            credit=Decimal("0.00"),
        )
        response = self.client.post(
            reverse("entry_validate", args=[entry.id])
            + f"?societe={self.company.id}"
        )
        self.assertEqual(response.status_code, 302)
        entry.refresh_from_db()
        self.assertFalse(entry.validated)
