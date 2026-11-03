from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounting.models import JournalEntry
from accounting.services import generate_portal
from companies.models import Company

from .models import Invoice
from .services import issue_invoice, pay_invoice


class InvoiceFlowTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("facture@example.com")
        self.company = Company.objects.create(
            owner=user,
            siren="812345679",
            denomination="Atelier Test",
            forme="SARL",
            regime="reel_simple",
            tva="reel",
            exercice_debut=date(2026, 1, 1),
        )
        generate_portal(self.company)
        self.client.force_login(user)
        self.invoice = Invoice.objects.create(
            company=self.company,
            number="BR-test",
            client_name="Client Démo",
            amount_ht=Decimal("100.00"),
            vat_rate=Decimal("20.00"),
            status="draft",
        )

    def test_issue_then_pay_posts_balanced_entries(self):
        issue_invoice(self.invoice)
        self.invoice.refresh_from_db()
        self.assertTrue(self.invoice.number.startswith("FAC-"))
        self.assertEqual(self.invoice.amount_ttc, Decimal("120.00"))
        sale = JournalEntry.objects.get(reference=self.invoice.number)
        debits = sum(line.debit for line in sale.lines.all())
        credits = sum(line.credit for line in sale.lines.all())
        self.assertEqual(debits, credits)
        self.assertEqual(debits, Decimal("120.00"))

        pay_invoice(self.invoice)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "paid")
        payment = JournalEntry.objects.get(reference=f"{self.invoice.number}-REG")
        self.assertEqual(sum(line.debit for line in payment.lines.all()), Decimal("120.00"))
        clients = sum(line.debit - line.credit for line in sale.lines.filter(account__code="411"))
        clients += sum(line.debit - line.credit for line in payment.lines.filter(account__code="411"))
        self.assertEqual(clients, Decimal("0.00"))

    def test_detail_and_edit_pages(self):
        detail = self.client.get(f"/factures/{self.invoice.id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Client Démo")
        self.assertContains(detail, "Modifier")
        edit = self.client.post(f"/factures/{self.invoice.id}/modifier/", {
            "client_name": "Client Modifié",
            "client_siren": "",
            "amount_ht": "150.00",
            "vat_rate": "20.00",
        })
        self.assertEqual(edit.status_code, 302)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.client_name, "Client Modifié")
        self.assertEqual(self.invoice.amount_ht, Decimal("150.00"))
        self.assertEqual(self.client.get("/cockpit/").status_code, 200)
        self.assertEqual(self.client.get("/compta/grand-livre/").status_code, 200)
        self.assertEqual(self.client.get("/compta/balance/").status_code, 200)
        self.assertEqual(self.client.get("/factures/").status_code, 200)
        self.assertContains(self.client.get("/factures/"), "Client Modifié")
