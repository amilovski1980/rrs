from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from fpdf import FPDF

from accounting.models import ChartAccount, EntryLine, Journal, JournalEntry
from accounting.services import generate_portal
from companies.models import Company
from documents.models import Invoice, Payment
from purchases.models import PurchaseInvoice, SupplierPayment

from .forms import ImportStatementForm, TransactionEntryForm
from .models import BankAccount, BankRule, BankTransaction
from .parsers import parse_csv, parse_ofx, parse_pdf
from .services import (
    create_entry_from_transaction,
    import_statement,
    match_transaction,
    reconcile_customer_receipt,
    reconcile_internal_transfer,
    reconcile_loan_payment,
    reconcile_supplier_payment,
    reconcile_vat_payment,
    unmatch_transaction,
)

CSV_SAMPLE = (
    "Date;Libellé;Débit;Crédit;Référence\n"
    "15/04/2026;VIR FOURNISSEUR;100,00;;V-001\n"
    "16/04/2026;VIR CLIENT DUPONT;;1 200,00;V-002\n"
).encode("utf-8")

OFX_SAMPLE = """OFXHEADER:100
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKTRANLIST>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260415<TRNAMT>-50.00<FITID>F1<NAME>FRAIS BANCAIRES</STMTTRN>
</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
""".encode("utf-8")


def pdf_statement() -> bytes:
    """Relevé PDF de test avec colonnes Débit / Crédit / Solde."""
    pdf = FPDF(format="A4", unit="mm")
    pdf.add_page()
    pdf.set_font("Helvetica", size=9)
    for x, label in (
        (15, "Date"),
        (38, "Libelle"),
        (105, "Debit"),
        (135, "Credit"),
        (168, "Solde"),
    ):
        pdf.text(x, 20, label)
    rows = [
        ("12/01/2026", "VIREMENT DUPONT", "", "1 250,00", "2 340,00"),
        ("15/01/2026", "PRLV EDF", "89,90", "", "2 250,10"),
        ("16/01/2026", "FRAIS BANCAIRES", "12,50", "", "2 237,60"),
    ]
    y = 30
    for row in rows:
        for x, value in zip((15, 38, 105, 135, 168), row):
            pdf.text(x, y, value)
        y += 7
    return bytes(pdf.output())


def blank_pdf() -> bytes:
    pdf = FPDF(format="A4", unit="mm")
    pdf.add_page()
    return bytes(pdf.output())


class BankTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            email="banque@example.fr", password="secret"
        )
        self.company = Company.objects.create(
            owner=self.user,
            siren="777888999",
            denomination="Atelier Banque",
            regime="reel_simple",
            tva="reel",
        )
        generate_portal(self.company)
        self.account = BankAccount.objects.create(
            company=self.company,
            label="Compte principal",
            ledger_account=self.company.accounts.get(code="512"),
            journal=Journal.objects.get(company=self.company, code="BQ"),
        )
        self.client.force_login(self.user)

    def _entry(self, label, amount, on_date=date(2026, 4, 15), credit=True):
        entry = JournalEntry.objects.create(
            company=self.company,
            journal=self.account.journal,
            date=on_date,
            label=label,
            reference="REG-001",
            validated=True,
        )
        bank_line = self.company.accounts.get(code="512")
        counterpart = self.company.accounts.get(code="401")
        if credit:
            EntryLine.objects.create(
                entry=entry, account=counterpart, debit=Decimal("0.00"), credit=abs(amount)
            )
            EntryLine.objects.create(
                entry=entry, account=bank_line, debit=abs(amount), credit=Decimal("0.00")
            )
        else:
            EntryLine.objects.create(
                entry=entry, account=counterpart, debit=abs(amount), credit=Decimal("0.00")
            )
            EntryLine.objects.create(
                entry=entry, account=bank_line, debit=Decimal("0.00"), credit=abs(amount)
            )
        return entry

    def test_csv_and_ofx_parsers(self):
        rows = parse_csv(CSV_SAMPLE)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].amount, Decimal("-100.00"))
        self.assertEqual(rows[1].amount, Decimal("1200.00"))
        ofx = parse_ofx(OFX_SAMPLE)
        self.assertEqual(len(ofx), 1)
        self.assertEqual(ofx[0].amount, Decimal("-50.00"))
        self.assertEqual(ofx[0].external_id, "F1")

    def test_pdf_parser_reads_debit_credit_columns(self):
        rows = parse_pdf(pdf_statement())
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].date, date(2026, 1, 12))
        self.assertEqual(rows[0].amount, Decimal("1250.00"))
        self.assertEqual(rows[0].label, "VIREMENT DUPONT")
        self.assertEqual(rows[1].amount, Decimal("-89.90"))
        self.assertEqual(rows[2].amount, Decimal("-12.50"))

    def test_pdf_import_is_idempotent_and_keeps_statement(self):
        first = import_statement(self.account, pdf_statement(), "releve.pdf")
        self.assertEqual(first.created, 3)
        self.assertEqual(first.statement.source_format, "pdf")
        self.assertEqual(first.statement.file_type, "application/pdf")
        second = import_statement(self.account, pdf_statement(), "releve.pdf")
        self.assertEqual(second.created, 0)
        self.assertEqual(second.duplicates, 3)
        self.assertEqual(BankTransaction.objects.count(), 3)

    def test_scanned_pdf_uses_ocr_text_fallback(self):
        text = (
            "12/01/2026 VIREMENT DUPONT 1 250,00\n"
            "15/01/2026 PRLV EDF -89,90\n"
        )
        with patch("banking.parsers.extract_receipt_text", return_value=text):
            rows = parse_pdf(blank_pdf())
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].amount, Decimal("1250.00"))
        self.assertEqual(rows[1].amount, Decimal("-89.90"))

    def test_import_form_accepts_pdf(self):
        form = ImportStatementForm(
            data={"account": self.account.pk},
            files={
                "file": SimpleUploadedFile(
                    "releve.pdf",
                    pdf_statement(),
                    content_type="application/pdf",
                )
            },
            company=self.company,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_import_is_idempotent(self):
        first = import_statement(self.account, CSV_SAMPLE, "releve.csv")
        self.assertEqual(first.created, 2)
        second = import_statement(self.account, CSV_SAMPLE, "releve.csv")
        self.assertEqual(second.created, 0)
        self.assertEqual(second.duplicates, 2)
        self.assertEqual(BankTransaction.objects.count(), 2)

    def test_imported_transaction_can_be_deleted(self):
        import_statement(self.account, CSV_SAMPLE, "releve.csv")
        transaction = BankTransaction.objects.get(label="VIR FOURNISSEUR")
        response = self.client.post(
            reverse("banking:transaction_delete", args=[transaction.id])
            + f"?societe={self.company.id}",
            {"next": reverse("banking:transactions") + f"?societe={self.company.id}"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            BankTransaction.objects.filter(pk=transaction.pk).exists()
        )

    def test_entry_form_auto_fills_reference_and_counterpart(self):
        ChartAccount.objects.get_or_create(
            company=self.company, code="6063", defaults={"label": "Achats"}
        )
        transaction = BankTransaction.objects.create(
            company=self.company,
            account=self.account,
            date=date(2026, 9, 7),
            label="EUROPEEN 5509493075 SOC NOUVELLE B O F 200355332026-08-21",
            amount=Decimal("-428.89"),
        )
        form = TransactionEntryForm(bank_transaction=transaction)
        self.assertEqual(form.initial.get("reference"), "5509493075")
        self.assertEqual(form.initial.get("counterpart_code"), "6063")

    def test_bank_fees_fall_back_to_an_expense_account(self):
        ChartAccount.objects.get_or_create(
            company=self.company, code="6063", defaults={"label": "Achats"}
        )
        transaction = BankTransaction.objects.create(
            company=self.company,
            account=self.account,
            date=date(2026, 9, 9),
            label="FRAIS BANCAIRES",
            amount=Decimal("-12.00"),
        )
        form = TransactionEntryForm(bank_transaction=transaction)
        self.assertEqual(form.initial.get("counterpart_code"), "6063")

    def test_incoming_entry_prefers_client_account(self):
        transaction = BankTransaction.objects.create(
            company=self.company,
            account=self.account,
            date=date(2026, 9, 8),
            label="VIR CLIENT DUPONT",
            amount=Decimal("1200.00"),
        )
        form = TransactionEntryForm(bank_transaction=transaction)
        self.assertEqual(form.initial.get("counterpart_code"), "411")

    def test_statement_file_is_kept_in_database_and_downloadable(self):
        result = import_statement(self.account, CSV_SAMPLE, "releve.csv")
        statement = result.statement
        statement.refresh_from_db()
        self.assertEqual(bytes(statement.file_data), CSV_SAMPLE)
        self.assertEqual(statement.file_type, "text/csv")
        response = self.client.get(
            reverse("banking:statement_file", args=[statement.id])
            + f"?societe={self.company.id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, CSV_SAMPLE)

    def test_auto_match_existing_entry(self):
        entry = self._entry("VIR FOURNISSEUR", Decimal("100.00"), credit=False)
        result = import_statement(self.account, CSV_SAMPLE, "releve.csv")
        transaction = BankTransaction.objects.get(label="VIR FOURNISSEUR")
        self.assertEqual(transaction.status, "matched")
        self.assertEqual(transaction.matched_entry_id, entry.id)
        self.assertGreaterEqual(result.matched, 1)

    def test_unmatched_transaction_can_create_entry(self):
        import_statement(self.account, CSV_SAMPLE, "releve.csv")
        transaction = BankTransaction.objects.get(label="VIR FOURNISSEUR")
        entry = create_entry_from_transaction(
            transaction,
            counterpart_code="627000",
            vat_amount=Decimal("0.00"),
            label="Frais bancaires",
        )
        lines = list(entry.lines.select_related("account"))
        debit = sum((line.debit for line in lines), Decimal("0.00"))
        credit = sum((line.credit for line in lines), Decimal("0.00"))
        self.assertEqual(debit, credit)
        transaction.refresh_from_db()
        self.assertEqual(transaction.status, "matched")
        self.assertEqual(transaction.match_type, "entry")

    def test_manual_match_and_unmatch(self):
        entry = self._entry("Frais bancaires", Decimal("50.00"), credit=False)
        import_statement(self.account, OFX_SAMPLE, "releve.ofx")
        transaction = BankTransaction.objects.get(label="FRAIS BANCAIRES")
        if transaction.status == "matched":
            unmatch_transaction(transaction)
        match_transaction(transaction, entry)
        transaction.refresh_from_db()
        self.assertEqual(transaction.status, "matched")
        self.assertEqual(transaction.matched_entry_id, entry.id)
        unmatch_transaction(transaction)
        transaction.refresh_from_db()
        self.assertEqual(transaction.status, "unmatched")

    def test_rule_matches_transaction(self):
        rule = BankRule.objects.create(
            company=self.company,
            name="Virements fournisseurs",
            label_contains="fournisseur",
            counterpart_account=self.company.accounts.get(code="622"),
        )
        import_statement(self.account, CSV_SAMPLE, "releve.csv")
        transaction = BankTransaction.objects.get(label="VIR FOURNISSEUR")
        self.assertTrue(rule.matches(transaction))
        self.assertFalse(rule.matches(BankTransaction.objects.get(label="VIR CLIENT DUPONT")))

    def test_pages_render(self):
        import_statement(self.account, CSV_SAMPLE, "releve.csv")
        transaction = BankTransaction.objects.first()
        for name in (
            "banking:dashboard",
            "banking:accounts",
            "banking:import",
            "banking:transactions",
            "banking:rules",
        ):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)
        for name in ("banking:transaction_detail", "banking:transaction_entry"):
            response = self.client.get(reverse(name, args=[transaction.pk]))
            self.assertEqual(response.status_code, 200, name)

        entry_page = self.client.get(
            reverse("banking:transaction_entry", args=[transaction.pk])
        )
        self.assertContains(entry_page, "data-banking-entry")
        self.assertContains(entry_page, "counterpart-accounts")
        self.assertContains(entry_page, "data-preview-status")
        self.assertContains(entry_page, "data-nature-section")
        self.assertContains(entry_page, "banking-entry.js")

    def test_reconcile_view_dispatches_customer_receipt(self):
        invoice = Invoice.objects.create(
            company=self.company,
            number="FAC-VIEW-1",
            client_name="Client Vue",
            amount_ht=Decimal("317.90"),
            vat_rate=Decimal("0.00"),
            status="issued",
        )
        transaction = BankTransaction.objects.create(
            company=self.company,
            account=self.account,
            date=date(2026, 6, 6),
            label="CB CLIENT VUE",
            amount=Decimal("316.80"),
            fingerprint="view-customer-1",
        )
        response = self.client.post(
            reverse("banking:transaction_entry", args=[transaction.pk]),
            {
                "nature": "customer_receipt",
                "date": "2026-06-06",
                "label": "CB Client Vue",
                "reference": "CB-VIEW",
                "customer_invoice": str(invoice.pk),
                "gross_amount": "317.90",
                "fee_amount": "1.10",
                "fee_account_code": "627000",
            },
        )
        self.assertEqual(response.status_code, 302)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "paid")
        transaction.refresh_from_db()
        self.assertEqual(transaction.nature, "customer_receipt")
        self.assertEqual(transaction.status, "matched")

    def test_customer_receipt_with_bank_fee(self):
        invoice = Invoice.objects.create(
            company=self.company,
            number="FAC-CLIENT-1",
            client_name="Client CB",
            amount_ht=Decimal("317.90"),
            vat_rate=Decimal("0.00"),
            status="issued",
        )
        transaction = BankTransaction.objects.create(
            company=self.company,
            account=self.account,
            date=date(2026, 6, 1),
            label="CB CLIENT",
            amount=Decimal("316.80"),
            fingerprint="client-cb-1",
        )
        entry = reconcile_customer_receipt(
            transaction,
            invoice=invoice,
            gross_amount=Decimal("317.90"),
            fee_amount=Decimal("1.10"),
            entry_date=date(2026, 6, 1),
        )
        lines = list(entry.lines.select_related("account"))
        self.assertEqual(sum(line.debit for line in lines), Decimal("317.90"))
        self.assertEqual(sum(line.credit for line in lines), Decimal("317.90"))
        self.assertTrue(any(line.account.code == "627000" and line.debit == Decimal("1.10") for line in lines))
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "paid")
        self.assertEqual(Payment.objects.get(invoice=invoice).amount, Decimal("317.90"))
        transaction.refresh_from_db()
        self.assertEqual(transaction.nature, "customer_receipt")
        self.assertEqual(transaction.matched_entry_id, entry.id)

    def test_supplier_payment_with_bank_fee(self):
        purchase = PurchaseInvoice.objects.create(
            company=self.company,
            supplier_name="Fournisseur Test",
            number="ACH-TEST-1",
            invoice_date=date(2026, 6, 1),
            amount_ht=Decimal("1000.00"),
            amount_vat=Decimal("0.00"),
            amount_ttc=Decimal("1000.00"),
            status="approved",
        )
        transaction = BankTransaction.objects.create(
            company=self.company,
            account=self.account,
            date=date(2026, 6, 2),
            label="VIR FOURNISSEUR",
            amount=Decimal("-1010.00"),
            fingerprint="supplier-pay-1",
        )
        entry = reconcile_supplier_payment(
            transaction,
            invoice=purchase,
            gross_amount=Decimal("1000.00"),
            fee_amount=Decimal("10.00"),
            entry_date=date(2026, 6, 2),
        )
        lines = list(entry.lines.select_related("account"))
        self.assertTrue(any(line.account.code == "401" and line.debit == Decimal("1000.00") for line in lines))
        self.assertTrue(any(line.account.code == "627000" and line.debit == Decimal("10.00") for line in lines))
        self.assertTrue(any(line.account.code == "512" and line.credit == Decimal("1010.00") for line in lines))
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, "paid")
        self.assertEqual(
            SupplierPayment.objects.get(invoice=purchase).amount, Decimal("1000.00")
        )
        transaction.refresh_from_db()
        self.assertEqual(transaction.nature, "supplier_payment")

    def test_loan_payment_splits_principal_and_interest(self):
        transaction = BankTransaction.objects.create(
            company=self.company,
            account=self.account,
            date=date(2026, 6, 3),
            label="ECHEANCE PRET",
            amount=Decimal("-596.70"),
            fingerprint="loan-1",
        )
        entry = reconcile_loan_payment(
            transaction,
            principal=Decimal("500.00"),
            interest=Decimal("96.70"),
        )
        lines = list(entry.lines.select_related("account"))
        self.assertTrue(any(line.account.code == "164" and line.debit == Decimal("500.00") for line in lines))
        self.assertTrue(any(line.account.code == "661" and line.debit == Decimal("96.70") for line in lines))
        self.assertTrue(any(line.account.code == "512" and line.credit == Decimal("596.70") for line in lines))
        transaction.refresh_from_db()
        self.assertEqual(transaction.nature, "loan_payment")

    def test_vat_payment_does_not_create_an_expense(self):
        transaction = BankTransaction.objects.create(
            company=self.company,
            account=self.account,
            date=date(2026, 6, 4),
            label="TVA A PAYER",
            amount=Decimal("-200.00"),
            fingerprint="vat-1",
        )
        entry = reconcile_vat_payment(transaction, vat_account_code="44571")
        lines = list(entry.lines.select_related("account"))
        self.assertTrue(any(line.account.code == "44571" and line.debit == Decimal("200.00") for line in lines))
        self.assertFalse(any(line.account.code.startswith("6") for line in lines))
        transaction.refresh_from_db()
        self.assertEqual(transaction.nature, "vat_payment")

    def test_internal_transfer_has_no_charge(self):
        other_ledger = ChartAccount.objects.create(
            company=self.company, code="5121", label="Banque secondaire"
        )
        other = BankAccount.objects.create(
            company=self.company,
            label="Compte secondaire",
            ledger_account=other_ledger,
            journal=self.account.journal,
        )
        transaction = BankTransaction.objects.create(
            company=self.company,
            account=self.account,
            date=date(2026, 6, 5),
            label="VIREMENT COMPTE SECONDAIRE",
            amount=Decimal("-100.00"),
            fingerprint="transfer-1",
        )
        entry = reconcile_internal_transfer(transaction, other_account=other)
        lines = list(entry.lines.select_related("account"))
        self.assertTrue(any(line.account.code == "5121" and line.debit == Decimal("100.00") for line in lines))
        self.assertTrue(any(line.account.code == "512" and line.credit == Decimal("100.00") for line in lines))
        self.assertFalse(any(line.account.code.startswith("6") for line in lines))
        transaction.refresh_from_db()
        self.assertEqual(transaction.nature, "internal_transfer")
