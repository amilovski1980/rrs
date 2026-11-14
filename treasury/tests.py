from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounting.models import EntryLine, Journal, JournalEntry
from accounting.services import generate_portal
from companies.models import Company
from documents.models import Invoice
from purchases.models import PurchaseInvoice

from .services import build_snapshot


class TreasuryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            email="tresorerie@example.fr", password="secret"
        )
        self.company = Company.objects.create(
            owner=self.user,
            siren="888999000",
            denomination="Atelier Trésorerie",
            regime="reel_simple",
            tva="reel",
        )
        generate_portal(self.company)
        self.today = timezone.localdate()
        self.client.force_login(self.user)
        self._bank_entries()

    def _bank_entries(self):
        journal = Journal.objects.get(company=self.company, code="BQ")
        bank = self.company.accounts.get(code="512")
        supplier = self.company.accounts.get(code="401")
        cash = self.company.accounts.get(code="530")
        entry = JournalEntry.objects.create(
            company=self.company,
            journal=journal,
            date=self.today,
            label="Apport bancaire",
            reference="TRESO-1",
            validated=True,
        )
        EntryLine.objects.create(entry=entry, account=bank, debit=Decimal("2000.00"), credit=Decimal("0.00"))
        EntryLine.objects.create(entry=entry, account=supplier, debit=Decimal("0.00"), credit=Decimal("2000.00"))

        cash_journal = self.company.journals.filter(code="CA").first() or journal
        cash_entry = JournalEntry.objects.create(
            company=self.company,
            journal=cash_journal,
            date=self.today,
            label="Caisse",
            reference="TRESO-2",
            validated=True,
        )
        EntryLine.objects.create(entry=cash_entry, account=cash, debit=Decimal("300.00"), credit=Decimal("0.00"))
        EntryLine.objects.create(entry=cash_entry, account=supplier, debit=Decimal("0.00"), credit=Decimal("300.00"))

    def _receivable(self, number="FAC-2026-100", due_in=10, ht="1000.00"):
        return Invoice.objects.create(
            company=self.company,
            number=number,
            client_name="Client Test",
            amount_ht=Decimal(ht),
            vat_rate=Decimal("20.00"),
            status="issued",
            due_date=self.today + timedelta(days=due_in),
        )

    def _payable(self, number="ACH-2026-100", due_in=5, ht="500.00"):
        return PurchaseInvoice.objects.create(
            company=self.company,
            supplier_name="Fournisseur Test",
            number=number,
            invoice_date=self.today,
            due_date=self.today + timedelta(days=due_in),
            amount_ht=Decimal(ht),
            amount_vat=Decimal("100.00"),
            amount_ttc=Decimal("600.00"),
            status="approved",
        )

    def test_position_and_forecast(self):
        self._receivable()
        self._payable()
        snapshot = build_snapshot(self.company)

        self.assertEqual(snapshot.position, Decimal("2300.00"))
        self.assertEqual(snapshot.receivables_total, Decimal("1200.00"))
        self.assertEqual(snapshot.payables_total, Decimal("600.00"))
        self.assertEqual(snapshot.net_position, Decimal("2900.00"))
        self.assertEqual(snapshot.forecast.total_in, Decimal("1200.00"))
        self.assertEqual(snapshot.forecast.total_out, Decimal("600.00"))
        self.assertEqual(len(snapshot.forecast.weeks), 13)
        self.assertEqual(
            snapshot.forecast.weeks[-1]["balance"], Decimal("2900.00")
        )

    def test_overdue_and_aging(self):
        self._receivable(due_in=-10)
        self._payable(due_in=-3)
        snapshot = build_snapshot(self.company)
        self.assertEqual(snapshot.overdue_receivables, 1)
        self.assertEqual(snapshot.overdue_payables, 1)
        self.assertEqual(snapshot.receivables_aging["d1_30"], Decimal("1200.00"))
        self.assertEqual(snapshot.payables_aging["d1_30"], Decimal("600.00"))

    def test_pages_and_export(self):
        self._receivable()
        self._payable()
        response = self.client.get(reverse("treasury:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Prévisionnel 13 semaines")
        response = self.client.get(reverse("treasury:export"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertIn("Semaine", response.content.decode("utf-8"))
