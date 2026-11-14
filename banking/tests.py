from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounting.models import EntryLine, Journal, JournalEntry
from accounting.services import generate_portal
from companies.models import Company

from .models import BankAccount, BankRule, BankTransaction
from .parsers import parse_csv, parse_ofx
from .services import (
    create_entry_from_transaction,
    import_statement,
    match_transaction,
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

    def test_import_is_idempotent(self):
        first = import_statement(self.account, CSV_SAMPLE, "releve.csv")
        self.assertEqual(first.created, 2)
        second = import_statement(self.account, CSV_SAMPLE, "releve.csv")
        self.assertEqual(second.created, 0)
        self.assertEqual(second.duplicates, 2)
        self.assertEqual(BankTransaction.objects.count(), 2)

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
