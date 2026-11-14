from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounting.models import JournalEntry
from accounting.services import generate_portal
from companies.models import Company

from .models import Invoice
from .services import delete_payment, issue_invoice, register_payment


class CustomerPaymentTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            email="paiements@example.fr", password="secret"
        )
        self.company = Company.objects.create(
            owner=self.user,
            siren="333444555",
            denomination="Atelier Paiements",
            regime="reel_simple",
            tva="reel",
            payment_terms_days=45,
        )
        generate_portal(self.company)
        self.invoice = Invoice.objects.create(
            company=self.company,
            number="FAC-2026-00001",
            client_name="Client Test",
            amount_ht=Decimal("100.00"),
            vat_rate=Decimal("20.00"),
            status="issued",
        )

    def test_delete_payment_removes_bank_entry(self):
        payment = register_payment(
            self.invoice,
            amount=Decimal("120.00"),
            method="transfer",
            reference="REG-001",
        )
        entry_id = payment.journal_entry_id
        self.assertIsNotNone(entry_id)
        self.assertTrue(JournalEntry.objects.filter(pk=entry_id).exists())

        delete_payment(payment)

        self.assertFalse(JournalEntry.objects.filter(pk=entry_id).exists())
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "issued")

    def test_issue_sets_due_date_from_company_terms(self):
        draft = Invoice.objects.create(
            company=self.company,
            number="BR-TEMP",
            client_name="Client Test",
            amount_ht=Decimal("100.00"),
            vat_rate=Decimal("20.00"),
            status="draft",
        )
        issue_invoice(draft)
        draft.refresh_from_db()
        self.assertIsNotNone(draft.due_date)
        self.assertEqual(
            draft.due_date,
            draft.created_at.date() + timedelta(days=45),
        )

    def test_explicit_due_date_drives_late_status(self):
        self.invoice.due_date = self.invoice.created_at.date() - timedelta(days=1)
        self.invoice.save(update_fields=["due_date"])
        self.assertTrue(self.invoice.is_late)
