"""Tests unitaires du connecteur e-mail : parsing, doublons, validation."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounting.models import ChartAccount
from accounting.services import generate_portal
from companies.models import Company

from .crypto import decrypt_text, encrypt_text
from .matching import find_matching_supplier, normalize_vat
from .models import MailboxConfig, ProcessedEmail, Supplier, SupplierInvoiceDraft
from .parsers import parse_attachment
from .parsers.pdf_invoice import _extract_amounts, _find_date
from .parsers.xml_invoice import parse_xml
from .providers.base import MailAttachment, MailMessage
from .services import sync_mailbox, validate_draft
from purchases.models import PurchaseInvoice


UBL_INVOICE = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>FAC-2026-0042</cbc:ID>
  <cbc:IssueDate>2026-02-10</cbc:IssueDate>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyName><cbc:Name>Plomberie Martin</cbc:Name></cac:PartyName>
      <cac:PartyLegalEntity><cbc:CompanyID>12345678901234</cbc:CompanyID></cac:PartyLegalEntity>
      <cac:PartyTaxScheme><cbc:CompanyID>FR12345678901</cbc:CompanyID></cac:PartyTaxScheme>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:TaxTotal>
    <cbc:TaxAmount>200.00</cbc:TaxAmount>
    <cac:TaxSubtotal><cbc:Percent>20.00</cbc:Percent></cac:TaxSubtotal>
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:TaxExclusiveAmount>1000.00</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount>1200.00</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount>1200.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  <cac:InvoiceLine>
    <cac:Item><cbc:Description>Réparation chauffe-eau</cbc:Description></cac:Item>
  </cac:InvoiceLine>
</Invoice>""".encode("utf-8")

CII_INVOICE = """<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice
    xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
    xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
    xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
  <rsm:ExchangedDocument>
    <ram:ID>FA-2026-001</ram:ID>
    <ram:IssueDateTime>
      <udt:DateTimeString format="102">20260212</udt:DateTimeString>
    </ram:IssueDateTime>
  </rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
    <ram:ApplicableHeaderTradeAgreement>
      <ram:SellerTradeParty>
        <ram:Name>Électricité Dupont</ram:Name>
        <ram:SpecifiedTaxRegistration>
          <ram:ID schemeID="VA">FR98765432109</ram:ID>
        </ram:SpecifiedTaxRegistration>
      </ram:SellerTradeParty>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:ApplicableTradeTax>
        <ram:RateApplicablePercent>20.00</ram:RateApplicablePercent>
      </ram:ApplicableTradeTax>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:LineTotalAmount>500.00</ram:LineTotalAmount>
        <ram:TaxTotalAmount currencyID="EUR">100.00</ram:TaxTotalAmount>
        <ram:GrandTotalAmount>600.00</ram:GrandTotalAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>""".encode("utf-8")


class CryptoTests(TestCase):
    def test_roundtrip(self):
        token = encrypt_text("ya29.super-secret")
        self.assertNotIn("ya29", token)
        self.assertEqual(decrypt_text(token), "ya29.super-secret")

    def test_empty_and_invalid(self):
        self.assertEqual(decrypt_text(""), "")
        self.assertEqual(decrypt_text("pas-un-jeton"), "")


class ParserTests(TestCase):
    def test_ubl(self):
        invoice = parse_xml(UBL_INVOICE)
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.source, "ubl")
        self.assertEqual(invoice.supplier_name, "Plomberie Martin")
        self.assertEqual(invoice.supplier_siret, "12345678901234")
        self.assertEqual(invoice.supplier_vat, "FR12345678901")
        self.assertEqual(invoice.invoice_number, "FAC-2026-0042")
        self.assertEqual(invoice.invoice_date, date(2026, 2, 10))
        self.assertEqual(invoice.amount_ht, Decimal("1000.00"))
        self.assertEqual(invoice.amount_vat, Decimal("200.00"))
        self.assertEqual(invoice.amount_ttc, Decimal("1200.00"))
        self.assertEqual(invoice.vat_rate, Decimal("20.00"))

    def test_cii(self):
        invoice = parse_xml(CII_INVOICE)
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.source, "cii")
        self.assertEqual(invoice.supplier_name, "Électricité Dupont")
        self.assertEqual(invoice.supplier_vat, "FR98765432109")
        self.assertEqual(invoice.invoice_number, "FA-2026-001")
        self.assertEqual(invoice.invoice_date, date(2026, 2, 12))
        self.assertEqual(invoice.amount_ht, Decimal("500.00"))
        self.assertEqual(invoice.amount_vat, Decimal("100.00"))
        self.assertEqual(invoice.amount_ttc, Decimal("600.00"))

    def test_invalid_xml(self):
        self.assertIsNone(parse_xml(b"<facture>cassee</facture>"))

    def test_pdf_text_amounts(self):
        text = (
            "Plomberie Martin\n"
            "Facture N° FA-2026-001\n"
            "Date : 12/02/2026\n"
            "Total HT 1 000,00 €\n"
            "TVA 20 % 200,00 €\n"
            "Total TTC 1 200,00 €\n"
        )
        ht, vat, ttc = _extract_amounts(text)
        self.assertEqual(ht, Decimal("1000.00"))
        self.assertEqual(vat, Decimal("200.00"))
        self.assertEqual(ttc, Decimal("1200.00"))
        self.assertEqual(_find_date(text), date(2026, 2, 12))

    def test_dispatch_by_extension(self):
        self.assertEqual(parse_attachment("facture.xml", UBL_INVOICE).source, "ubl")
        self.assertIsNone(parse_attachment("facture.pdf", b"%PDF-1.4 casse"))
        self.assertIsNone(parse_attachment("facture.txt", b"hello"))


class MatchingTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(email="dirigeant@example.fr", password="secret")
        self.company = Company.objects.create(
            owner=self.user,
            siren="123456789",
            denomination="BTP Test",
            regime="reel_simple",
            tva="reel",
        )

    def test_match_by_siret_then_vat_then_domain(self):
        supplier = Supplier.objects.create(
            company=self.company,
            name="Plomberie Martin",
            siret="12345678901234",
            tva_intra="FR12345678901",
            email_domain="plomberie-martin.fr",
        )
        self.assertEqual(
            find_matching_supplier(self.company, siret="123 456 789 01234").pk,
            supplier.pk,
        )
        self.assertEqual(
            find_matching_supplier(self.company, vat="fr 12 345 678 901").pk,
            supplier.pk,
        )
        self.assertEqual(
            find_matching_supplier(self.company, email="facture@plomberie-martin.fr").pk,
            supplier.pk,
        )
        self.assertIsNone(find_matching_supplier(self.company, name="Inconnu"))

    def test_normalize_vat(self):
        self.assertEqual(normalize_vat("fr 12 345 678 901"), "FR12345678901")


class FakeAdapter:
    def __init__(self, messages, payloads):
        self.messages = messages
        self.payloads = payloads

    def fetch_account(self):
        return "compta@example.fr", "42"

    def list_messages(self, *, folder="", since=None):
        return self.messages

    def open_attachment(self, message, attachment):
        return self.payloads[attachment.filename]


class SyncAndValidateTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(email="dirigeant@example.fr", password="secret")
        self.company = Company.objects.create(
            owner=self.user,
            siren="987654321",
            denomination="BTP Test",
            regime="reel_simple",
            tva="reel",
        )
        generate_portal(self.company)
        self.config = MailboxConfig.objects.create(
            company=self.company,
            provider="gmail",
            is_active=True,
            frequency_minutes=30,
        )
        self.message = MailMessage(
            message_id="gmail-msg-1",
            subject="Facture février",
            from_email="contact@plomberie-martin.fr",
            from_name="Plomberie Martin",
            attachments=[MailAttachment(filename="facture.xml", size=len(UBL_INVOICE))],
        )
        self.adapter = FakeAdapter([self.message], {"facture.xml": UBL_INVOICE})

    def test_sync_is_idempotent(self):
        first = sync_mailbox(self.config, adapter=self.adapter)
        self.assertEqual(first.imported, 1)
        self.assertEqual(SupplierInvoiceDraft.objects.count(), 1)

        second = sync_mailbox(self.config, adapter=self.adapter)
        self.assertEqual(second.imported, 0)
        self.assertEqual(SupplierInvoiceDraft.objects.count(), 1)
        self.assertEqual(ProcessedEmail.objects.count(), 1)
        self.assertEqual(ProcessedEmail.objects.get().status, "imported")

    def test_draft_prefilled_from_xml(self):
        sync_mailbox(self.config, adapter=self.adapter)
        draft = SupplierInvoiceDraft.objects.get()
        self.assertEqual(draft.invoice_number, "FAC-2026-0042")
        self.assertEqual(draft.amount_ttc, Decimal("1200.00"))
        self.assertEqual(draft.journal.code, "ACH")
        self.assertEqual(draft.charge_account_code, "606000")
        self.assertEqual(draft.status, "pending")
        self.assertTrue(draft.attachment_name.endswith(".xml"))

    def test_validate_creates_balanced_entry(self):
        sync_mailbox(self.config, adapter=self.adapter)
        draft = SupplierInvoiceDraft.objects.get()
        entry = validate_draft(draft, supplier_name="Plomberie Martin")

        self.assertTrue(entry.validated)
        self.assertEqual(entry.journal.code, "ACH")
        self.assertEqual(entry.reference, "FAC-2026-0042")

        lines = list(entry.lines.select_related("account"))
        total_debit = sum((line.debit for line in lines), Decimal("0.00"))
        total_credit = sum((line.credit for line in lines), Decimal("0.00"))
        self.assertEqual(total_debit, total_credit)
        self.assertEqual(total_debit, Decimal("1200.00"))

        supplier_line = next(line for line in lines if line.credit > 0)
        self.assertTrue(supplier_line.account.code.startswith("401"))
        charge_line = next(
            line for line in lines if line.account.code == "606000"
        )
        self.assertEqual(charge_line.debit, Decimal("1000.00"))
        self.assertTrue(ChartAccount.objects.filter(company=self.company, code="606000").exists())

        draft.refresh_from_db()
        self.assertEqual(draft.status, "validated")
        self.assertEqual(draft.entry_id, entry.id)
        self.assertIsNotNone(draft.validated_at)

        purchase = PurchaseInvoice.objects.get(mailsync_draft=draft)
        self.assertEqual(purchase.status, "approved")
        self.assertEqual(purchase.journal_entry_id, entry.id)
        self.assertEqual(purchase.amount_ttc, Decimal("1200.00"))

    def test_validate_is_not_replayable(self):
        sync_mailbox(self.config, adapter=self.adapter)
        draft = SupplierInvoiceDraft.objects.get()
        validate_draft(draft, supplier_name="Plomberie Martin")
        with self.assertRaises(Exception):
            validate_draft(draft, supplier_name="Plomberie Martin")
        self.assertEqual(entry_count := self.company.entries.count(), 1)

    def test_inactive_mailbox_does_nothing(self):
        self.config.is_active = False
        self.config.save(update_fields=["is_active"])
        result = sync_mailbox(self.config, adapter=self.adapter)
        self.assertEqual(result.imported, 0)
        self.assertEqual(SupplierInvoiceDraft.objects.count(), 0)


class ViewTests(TestCase):
    """Les écrans du connecteur se rendent et restent isolés par société."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(email="dirigeant@example.fr", password="secret")
        self.company = Company.objects.create(
            owner=self.user,
            siren="111222333",
            denomination="Menuiserie Test",
            regime="reel_simple",
            tva="reel",
        )
        generate_portal(self.company)
        self.client.force_login(self.user)

    def test_settings_page_renders(self):
        response = self.client.get(reverse("mailsync:settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Connecter mon compte Gmail")

    def test_drafts_page_renders(self):
        response = self.client.get(reverse("mailsync:drafts"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Factures reçues par e-mail")

    def test_connect_without_google_credentials_redirects(self):
        response = self.client.get(reverse("mailsync:connect", args=["gmail"]))
        self.assertRedirects(response, reverse("mailsync:settings"))

    def test_draft_detail_is_scoped_to_company(self):
        draft = SupplierInvoiceDraft.objects.create(
            company=self.company,
            proposed_supplier_name="Fournisseur Test",
            invoice_number="F-2026-1",
            amount_ht=Decimal("100.00"),
            amount_vat=Decimal("20.00"),
            amount_ttc=Decimal("120.00"),
            charge_account_code="606000",
            vat_account_code="445660",
            supplier_account_root="401",
            source="pdf",
            status="pending",
        )
        response = self.client.get(reverse("mailsync:draft_detail", args=[draft.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Valider en journal ACH")

        other_user = get_user_model().objects.create_user(
            email="autre@example.fr", password="secret"
        )
        other_company = Company.objects.create(
            owner=other_user,
            siren="444555666",
            denomination="Autre société",
            regime="reel_simple",
            tva="reel",
        )
        self.client.force_login(other_user)
        response = self.client.get(reverse("mailsync:draft_detail", args=[draft.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(other_company.entries.count(), 0)
