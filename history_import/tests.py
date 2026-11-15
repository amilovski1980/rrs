import io
import zipfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounting.models import JournalEntry
from companies.models import Company
from documents.models import Invoice
from mailsync.models import Supplier
from purchases.models import PurchaseInvoice

from .models import ImportAuditEvent, ImportBatch, ImportDocument
from .services import (
    HistoricalImportError,
    add_upload,
    apply_tabular,
    batch_stats,
    create_batch,
    import_document,
    process_batch,
)


def ubl_invoice(*, number, supplier_name, supplier_id, customer_name, customer_id):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>{number}</cbc:ID>
  <cbc:IssueDate>2024-01-15</cbc:IssueDate>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyName><cbc:Name>{supplier_name}</cbc:Name></cac:PartyName>
      <cac:PartyLegalEntity><cbc:CompanyID>{supplier_id}</cbc:CompanyID></cac:PartyLegalEntity>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty>
    <cac:Party>
      <cac:PartyName><cbc:Name>{customer_name}</cbc:Name></cac:PartyName>
      <cac:PartyLegalEntity><cbc:CompanyID>{customer_id}</cbc:CompanyID></cac:PartyLegalEntity>
    </cac:Party>
  </cac:AccountingCustomerParty>
  <cac:TaxTotal>
    <cbc:TaxAmount>200.00</cbc:TaxAmount>
    <cac:TaxSubtotal><cbc:Percent>20.00</cbc:Percent></cac:TaxSubtotal>
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:TaxExclusiveAmount>1000.00</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount>1200.00</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount>1200.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
</Invoice>""".encode("utf-8")


class HistoricalImportTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            email="migration@example.fr", password="secret"
        )
        self.company = Company.objects.create(
            owner=self.user,
            siren="123456789",
            denomination="Menuiserie Historique",
            regime="reel_simple",
            tva="reel",
            source_data={"siret": "12345678901234"},
        )
        self.client.force_login(self.user)
        self.sale_xml = ubl_invoice(
            number="HIST-SALE-1",
            supplier_name="Menuiserie Historique",
            supplier_id="12345678901234",
            customer_name="Client Historique",
            customer_id="98765432109876",
        )
        self.purchase_xml = ubl_invoice(
            number="HIST-PURCHASE-1",
            supplier_name="Fournisseur Historique",
            supplier_id="98765432109876",
            customer_name="Menuiserie Historique",
            customer_id="12345678901234",
        )

    def _batch(self, *files):
        batch = create_batch(self.company, self.user)
        for name, payload in files:
            add_upload(
                batch,
                SimpleUploadedFile(name, payload, content_type="application/xml"),
                self.user,
            )
        return batch

    def test_uploaded_document_is_kept_in_database_and_downloadable(self):
        batch = self._batch(("vente.xml", self.sale_xml))
        document = batch.documents.get()
        self.assertEqual(bytes(document.file_data), self.sale_xml)
        response = self.client.get(
            reverse("history_import:document_file", args=[document.pk])
            + f"?societe={self.company.id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, self.sale_xml)

    def test_batch_process_json_exposes_activity_feed_and_progress(self):
        batch = self._batch(("vente.xml", self.sale_xml))
        response = self.client.post(
            reverse("history_import:batch_process", args=[batch.pk])
            + f"?societe={self.company.id}",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["pending"], 0)
        self.assertTrue(data["activities"])
        self.assertIn(
            "document_processed",
            [event["action"] for event in data["activities"]],
        )

    def test_sale_invoice_is_imported_as_archive_without_accounting_entry(self):
        batch = self._batch(("vente.xml", self.sale_xml))
        process_batch(batch, user=self.user)
        document = batch.documents.get()
        self.assertEqual(document.kind, "sale_invoice")
        self.assertEqual(document.status, "ready")
        import_document(document, user=self.user)

        document.refresh_from_db()
        self.assertEqual(document.status, "imported")
        invoice = Invoice.objects.get(company=self.company, number="HIST-SALE-1")
        self.assertEqual(invoice.source, "historical_import")
        self.assertEqual(invoice.status, "archived")
        self.assertEqual(invoice.client_name, "Client Historique")
        self.assertEqual(invoice.amount_ht, 1000)
        self.assertEqual(document.imported_invoice_id, invoice.id)
        self.assertEqual(JournalEntry.objects.filter(company=self.company).count(), 0)
        self.assertTrue(ImportAuditEvent.objects.filter(action="document_imported").exists())

    def test_purchase_invoice_is_imported_in_purchase_register_without_entry(self):
        batch = self._batch(("achat.xml", self.purchase_xml))
        process_batch(batch, user=self.user)
        document = batch.documents.get()
        self.assertEqual(document.kind, "purchase_invoice")
        self.assertTrue(document.seller_name)
        import_document(document, user=self.user)

        purchase = PurchaseInvoice.objects.get(
            company=self.company, number="HIST-PURCHASE-1"
        )
        self.assertEqual(purchase.source, "historical_import")
        self.assertEqual(purchase.status, "archived")
        self.assertTrue(Supplier.objects.filter(company=self.company).exists())
        self.assertEqual(JournalEntry.objects.filter(company=self.company).count(), 0)

    def test_existing_invoice_is_flagged_duplicate(self):
        Invoice.objects.create(
            company=self.company,
            number="HIST-SALE-1",
            client_name="Déjà présent",
            amount_ht=1000,
            vat_rate=20,
            status="issued",
        )
        batch = self._batch(("vente.xml", self.sale_xml))
        process_batch(batch, user=self.user)
        document = batch.documents.get()
        self.assertEqual(document.status, "duplicate")
        self.assertIn("déjà présente", document.duplicate_reason.lower())
        self.assertEqual(document.kind, "sale_invoice")
        self.assertEqual(document.imported_invoice.number, "HIST-SALE-1")

    def test_duplicate_file_is_not_processed_twice(self):
        batch = self._batch(
            ("vente-1.xml", self.sale_xml),
            ("vente-2.xml", self.sale_xml),
        )
        process_batch(batch, user=self.user)
        stats = batch_stats(batch)
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["duplicates"], 1)
        self.assertEqual(stats["ready"], 1)
        self.assertEqual(ImportDocument.objects.filter(status="imported").count(), 0)

    def test_zip_path_traversal_is_rejected(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("../facture.xml", self.sale_xml)
        batch = create_batch(self.company, self.user)
        with self.assertRaises(HistoricalImportError):
            add_upload(
                batch,
                SimpleUploadedFile(
                    "archive.zip", buffer.getvalue(), content_type="application/zip"
                ),
                self.user,
            )

    def test_upload_view_accepts_multiple_files(self):
        response = self.client.post(
            reverse("history_import:upload"),
            {
                "files": [
                    SimpleUploadedFile("vente.xml", self.sale_xml, content_type="application/xml"),
                    SimpleUploadedFile("achat.xml", self.purchase_xml, content_type="application/xml"),
                ],
                "kind_hint": "",
                "label": "Test mobile",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        batch = ImportBatch.objects.get(company=self.company)
        self.assertEqual(batch.documents.count(), 2)
        self.assertContains(response, "Test mobile")

    def test_document_file_is_private_to_company(self):
        batch = self._batch(("vente.xml", self.sale_xml))
        process_batch(batch, user=self.user)
        document = batch.documents.get()
        User = get_user_model()
        other_user = User.objects.create_user(
            email="autre-migration@example.fr", password="secret"
        )
        Company.objects.create(
            owner=other_user,
            siren="987654321",
            denomination="Autre société",
            regime="reel_simple",
            tva="reel",
        )
        self.client.force_login(other_user)
        response = self.client.get(
            reverse("history_import:document_file", args=[document.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_batch_page_renders(self):
        batch = self._batch(("vente.xml", self.sale_xml))
        process_batch(batch, user=self.user)
        response = self.client.get(
            reverse("history_import:batch", args=[batch.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Historique")
        self.assertContains(response, "Importer la sélection")


from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from companies.models import Company


class TabularImportTests(HistoricalImportTestCase):
    """Import universel : encaissements SumUp et catalogue de caisse."""

    SUMUP_CSV = (
        "Date,Transaction ID,Payment Method,Status,Gross Amount,Tax,Fee,Net Payout,Currency\r\n"
        "2026-11-14 14:32:10,TXN-984321,Card (Contactless),Successful,25.00,4.17,0.44,24.56,EUR\r\n"
        "2026-11-14 15:10:05,TXN-984322,Cash,Successful,12.50,2.08,0.00,12.50,EUR\r\n"
    ).encode("utf-8")

    CATALOGUE_CSV = (
        "Item id,Variant id,Item name,Variant name,Category,Price,Tax rate (%),SKU,Track inventory,Quantity\r\n"
        "a1b2c3d4,v1w2x3y4,Espresso,Single,Hot Drinks,2.50,10,COF-001,Yes,150\r\n"
        "a1b2c3d4,v5w6x7y8,Espresso,Double,Hot Drinks,3.50,10,COF-002,Yes,150\r\n"
    ).encode("utf-8")

    PRODUCT_SALES_CSV = (
        "Product,Store,Category,Quantity,Unit of measure,Sales amount excluding tax,"
        "Tax amount,Sales amount including tax,Gross Margin\r\n"
        "Café Espresso,Boutique Paris,Boissons,10,Unit,15.00,1.50,16.50,12.00\r\n"
        "Café Espresso,Boutique Lyon,Boissons,4,Unit,6.00,0.60,6.60,4.80\r\n"
        "T-shirt Logo,Boutique Lyon,Merchandising,2,Unit,39.00,7.80,46.80,20.00\r\n"
    ).encode("utf-8")

    def test_product_sales_csv_creates_products(self):
        from documents.models import Product

        batch = self._batch(("ventes-par-produit.csv", self.PRODUCT_SALES_CSV))
        process_batch(batch, user=self.user)
        document = batch.documents.get()
        self.assertEqual(document.kind, "product_sales")
        self.assertEqual(document.status, "ready")
        totals = document.extracted["totals"]
        self.assertEqual(totals["count"], 3)
        self.assertEqual(totals["produits"], 2)
        self.assertEqual(totals["ht"], "60.00")
        self.assertEqual(totals["tax"], "9.90")
        self.assertEqual(totals["ttc"], "69.90")

        summary = apply_tabular(document)
        self.assertEqual(summary["created"], 2)
        document.refresh_from_db()
        self.assertEqual(document.status, "imported")
        espresso = Product.objects.get(company=self.company, label="Café Espresso")
        # 21,00 € HT pour 14 unités vendues → PU 1,50 · TVA 10 %
        self.assertEqual(espresso.unit_price, Decimal("1.50"))
        self.assertEqual(espresso.vat_rate, Decimal("10.00"))
        shirt = Product.objects.get(company=self.company, label="T-shirt Logo")
        self.assertEqual(shirt.unit_price, Decimal("19.50"))
        self.assertEqual(shirt.vat_rate, Decimal("20.00"))
        # Idempotence : réappliquer ne recrée rien.
        self.assertEqual(apply_tabular(document)["created"], 0)

    def test_sumup_csv_is_detected_and_applied(self):
        from banking.models import BankAccount, BankTransaction

        batch = self._batch(("sumup.csv", self.SUMUP_CSV))
        process_batch(batch, user=self.user)
        document = batch.documents.get()
        self.assertEqual(document.kind, "sumup_transactions")
        self.assertEqual(document.status, "ready")
        self.assertEqual(document.extracted["totals"]["net"], "37.06")
        self.assertEqual(document.extracted["totals"]["gross"], "37.50")

        summary = apply_tabular(document)
        self.assertEqual(summary["created"], 2)
        document.refresh_from_db()
        self.assertEqual(document.status, "imported")
        transactions = BankTransaction.objects.filter(company=self.company)
        self.assertEqual(transactions.count(), 2)
        self.assertEqual(
            transactions.filter(label__icontains="TXN-984321").first().amount,
            Decimal("24.56"),
        )
        account = BankAccount.objects.get(company=self.company, label="SUMUP")
        for transaction in transactions:
            self.assertEqual(transaction.account_id, account.id)
        # Idempotence : réappliquer ne recrée rien.
        self.assertEqual(apply_tabular(document)["created"], 0)

    def test_catalogue_csv_creates_products(self):
        from documents.models import Product

        batch = self._batch(("catalogue.csv", self.CATALOGUE_CSV))
        process_batch(batch, user=self.user)
        document = batch.documents.get()
        self.assertEqual(document.kind, "catalogue")
        self.assertEqual(document.status, "ready")
        summary = apply_tabular(document)
        self.assertEqual(summary["created"], 2)
        self.assertEqual(Product.objects.filter(company=self.company).count(), 2)
        double = Product.objects.get(company=self.company, label="Espresso — Double")
        self.assertEqual(double.unit_price, Decimal("3.50"))
        self.assertEqual(double.vat_rate, Decimal("10.00"))
        # Réapplication sans changement : rien ne se duplique.
        self.assertEqual(apply_tabular(document)["skipped"], 2)
        self.assertEqual(Product.objects.filter(company=self.company).count(), 2)
