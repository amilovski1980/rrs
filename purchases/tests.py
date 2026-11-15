from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounting.models import JournalEntry
from accounting.services import generate_portal
from companies.models import Company
from mailsync.models import Supplier

from .models import PurchaseInvoice, SupplierPayment
from .services import (
    delete_supplier_payment,
    post_purchase,
    register_supplier_payment,
)


class PurchaseTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            email="achats@example.fr", password="secret"
        )
        self.company = Company.objects.create(
            owner=self.user,
            siren="555666777",
            denomination="Atelier Achats",
            regime="reel_simple",
            tva="reel",
            payment_terms_days=45,
        )
        generate_portal(self.company)
        self.supplier = Supplier.objects.create(
            company=self.company,
            name="Plomberie Martin",
            siret="12345678901234",
            payment_terms_days=30,
        )

    def _invoice(self, **overrides):
        data = {
            "company": self.company,
            "supplier": self.supplier,
            "supplier_name": self.supplier.name,
            "number": "FM-2026-001",
            "invoice_date": date(2026, 3, 10),
            "amount_ht": Decimal("1000.00"),
            "amount_vat": Decimal("200.00"),
            "amount_ttc": Decimal("1200.00"),
            "charge_account_code": "606000",
            "status": "draft",
        }
        data.update(overrides)
        return PurchaseInvoice.objects.create(**data)

    def test_purchase_form_exposes_mobile_wizard_steps(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("purchases:create") + f"?societe={self.company.id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-mobile-wizard")
        self.assertContains(response, "data-wizard-step", count=4)

    def test_pdf_import_creates_purchase_draft_and_keeps_file(self):
        self.client.force_login(self.user)
        payload = b"%PDF-1.4 facture fournisseur"
        upload = SimpleUploadedFile(
            "facture-fournisseur.pdf", payload, content_type="application/pdf"
        )
        parsed = {
            "client_name": "Plomberie Martin",
            "invoice_number": "FM-2026-009",
            "invoice_date": "10/03/2026",
            "amount_ht": Decimal("1000.00"),
            "amount_ttc": Decimal("1200.00"),
            "vat_rate": Decimal("20.00"),
        }
        with patch("purchases.views.extract_pdf_text", return_value="Facture"), patch(
            "purchases.views.parse_invoice_text", return_value=parsed
        ):
            response = self.client.post(
                reverse("purchases:import_pdf") + f"?societe={self.company.id}",
                {"pdf_file": upload},
            )
        self.assertEqual(response.status_code, 302)
        invoice = PurchaseInvoice.objects.get(
            company=self.company, number="FM-2026-009"
        )
        self.assertEqual(invoice.amount_ht, Decimal("1000.00"))
        self.assertEqual(invoice.amount_vat, Decimal("200.00"))
        self.assertEqual(bytes(invoice.attachment_data), payload)
        download = self.client.get(
            reverse("purchases:attachment", args=[invoice.id])
            + f"?societe={self.company.id}"
        )
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, payload)

    def test_post_purchase_creates_balanced_entry(self):
        invoice = self._invoice()
        entry = post_purchase(invoice)

        self.assertTrue(entry.validated)
        self.assertEqual(entry.journal.code, "ACH")
        lines = list(entry.lines.select_related("account"))
        debit = sum((line.debit for line in lines), Decimal("0.00"))
        credit = sum((line.credit for line in lines), Decimal("0.00"))
        self.assertEqual(debit, credit)
        self.assertEqual(debit, Decimal("1200.00"))
        self.assertTrue(
            any(line.account.code == "606000" and line.debit == Decimal("1000.00") for line in lines)
        )
        self.assertTrue(
            any(line.account.code.startswith("401") and line.credit == Decimal("1200.00") for line in lines)
        )

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "approved")
        self.assertEqual(invoice.journal_entry_id, entry.id)

    def test_payment_creates_bank_entry_and_marks_paid(self):
        invoice = self._invoice()
        post_purchase(invoice)
        payment = register_supplier_payment(
            invoice,
            amount=Decimal("1200.00"),
            method="transfer",
            paid_at=date(2026, 3, 20),
            reference="VIR-0042",
        )

        self.assertIsNotNone(payment.journal_entry_id)
        entry = payment.journal_entry
        self.assertEqual(entry.journal.code, "BQ")
        lines = list(entry.lines.select_related("account"))
        self.assertTrue(any(line.account.code.startswith("401") and line.debit == Decimal("1200.00") for line in lines))
        self.assertTrue(any(line.account.code == "512" and line.credit == Decimal("1200.00") for line in lines))

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "paid")
        self.assertEqual(invoice.amount_paid, Decimal("1200.00"))
        self.assertEqual(invoice.amount_remaining, Decimal("0.00"))

    def test_delete_payment_removes_entry(self):
        invoice = self._invoice()
        post_purchase(invoice)
        payment = register_supplier_payment(invoice, amount=Decimal("600.00"))
        entry_id = payment.journal_entry_id

        delete_supplier_payment(payment)

        self.assertFalse(JournalEntry.objects.filter(pk=entry_id).exists())
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "approved")
        self.assertEqual(invoice.amount_paid, Decimal("0.00"))

    def test_franchise_posts_ttc_to_charge(self):
        self.company.tva = "franchise"
        self.company.save(update_fields=["tva"])
        invoice = self._invoice()
        entry = post_purchase(invoice)
        lines = list(entry.lines.select_related("account"))
        self.assertEqual(len(lines), 2)
        charge = next(line for line in lines if line.debit > 0)
        self.assertEqual(charge.account.code, "606000")
        self.assertEqual(charge.debit, Decimal("1200.00"))

    def test_due_date_uses_supplier_terms(self):
        invoice = self._invoice()
        self.assertEqual(invoice.effective_due_date, date(2026, 4, 9))

    def test_pages_render(self):
        self.client.force_login(self.user)
        for name in ("purchases:dashboard", "purchases:list", "purchases:payments"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)

    def test_payment_view_records_settlement(self):
        invoice = self._invoice()
        post_purchase(invoice)
        self.client.force_login(self.user)
        response = self.client.get(reverse("purchases:pay", args=[invoice.pk]))
        self.assertEqual(response.status_code, 200)
        response = self.client.post(
            reverse("purchases:pay", args=[invoice.pk]),
            {
                "amount": "1200.00",
                "method": "transfer",
                "paid_at": date(2026, 3, 20).isoformat(),
                "reference": "VIR-VIEW",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "paid")


class SupplierPagesTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            email="fournisseurs@example.fr", password="secret"
        )
        self.company = Company.objects.create(
            owner=self.user,
            siren="222333444",
            denomination="Atelier Fournisseurs",
            regime="reel_simple",
            tva="reel",
        )
        self.client.force_login(self.user)

    def test_supplier_list_and_create(self):
        response = self.client.get(reverse("suppliers:list"))
        self.assertEqual(response.status_code, 200)
        response = self.client.post(
            reverse("suppliers:create"),
            {
                "name": "Fournisseur Test",
                "siret": "123 456 789 01234",
                "tva_intra": "FR 12 345 678 901",
                "email": "contact@fournisseur.fr",
                "payment_terms_days": 30,
                "is_active": "on",
            },
        )
        self.assertEqual(
            response.status_code,
            302,
            response.context["form"].errors.as_text() if response.context else "",
        )
        supplier = Supplier.objects.get(company=self.company, name="Fournisseur Test")
        self.assertEqual(supplier.siret, "12345678901234")
        self.assertEqual(supplier.email_domain, "fournisseur.fr")

    def test_supplier_detail_shows_invoices(self):
        supplier = Supplier.objects.create(
            company=self.company, name="Fournisseur Détail"
        )
        PurchaseInvoice.objects.create(
            company=self.company,
            supplier=supplier,
            supplier_name=supplier.name,
            number="DET-001",
            amount_ht=Decimal("100.00"),
            amount_vat=Decimal("20.00"),
            amount_ttc=Decimal("120.00"),
            status="approved",
        )
        response = self.client.get(reverse("suppliers:detail", args=[supplier.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "DET-001")
        self.assertContains(response, "120,00")

        response = self.client.get(reverse("suppliers:list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "120,00")
