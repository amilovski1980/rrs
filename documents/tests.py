from datetime import date
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounting.models import JournalEntry
from accounting.services import generate_portal
from companies.models import Company
from fpdf import FPDF

from .models import Client, CreditNote, Invoice, InvoiceLine, Payment, Product, Project, Quote
from .pdf_import import PdfImportError, extract_pdf_text, import_invoice_pdf, parse_invoice_text
from .services import (
    convert_quote_to_invoice,
    issue_credit_note,
    issue_invoice,
    pay_invoice,
    register_payment,
)


def _company(owner, siren="812345679", name="Atelier Test"):
    company = Company.objects.create(
        owner=owner,
        siren=siren,
        denomination=name,
        forme="SARL",
        regime="reel_simple",
        tva="reel",
        exercice_debut=date(2026, 1, 1),
    )
    generate_portal(company)
    return company


class InvoiceFlowTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("facture@example.com")
        self.company = _company(user)
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
        self.assertEqual(self.invoice.amount_paid, Decimal("120.00"))
        self.assertEqual(self.invoice.amount_remaining, Decimal("0.00"))

    def test_detail_and_edit_pages(self):
        detail = self.client.get(f"/factures/{self.invoice.id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Client Démo")
        self.assertContains(detail, "Modifier")
        edit = self.client.post(f"/factures/{self.invoice.id}/modifier/", {
            "client": "",
            "client_name": "Client Modifié",
            "client_siren": "",
            "project": "",
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

    def test_pdf_download(self):
        response = self.client.get(f"/factures/{self.invoice.id}/pdf/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn(b"attachment", response["Content-Disposition"].encode())


class TenantIsolationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.u1 = User.objects.create_user("a@example.com")
        self.u2 = User.objects.create_user("b@example.com")
        self.c1 = _company(self.u1, siren="111111111", name="Alpha")
        self.c2 = _company(self.u2, siren="222222222", name="Beta")
        self.client_a = Client.objects.create(company=self.c1, name="Client Alpha", siren="333333333")
        self.client_b = Client.objects.create(company=self.c2, name="Client Beta", siren="444444444")
        self.http = self.client
        self.http.force_login(self.u1)

    def test_client_list_is_scoped(self):
        response = self.http.get("/factures/clients/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Client Alpha")
        self.assertNotContains(response, "Client Beta")

    def test_cannot_open_other_company_client(self):
        response = self.http.get(f"/factures/clients/{self.client_b.id}/")
        self.assertEqual(response.status_code, 404)


class QuoteConversionTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("devis@example.com")
        self.company = _company(user, siren="555555555", name="Devis Co")
        self.http = self.client
        self.http.force_login(user)
        self.client_obj = Client.objects.create(company=self.company, name="Martin SA", siren="666666666")
        self.project = Project.objects.create(
            company=self.company, client=self.client_obj, name="Chantier Nord"
        )
        self.quote = Quote.objects.create(
            company=self.company,
            number="BR-devis1",
            client=self.client_obj,
            client_name="Martin SA",
            client_siren="666666666",
            project=self.project,
            amount_ht=Decimal("500.00"),
            vat_rate=Decimal("20.00"),
            status="sent",
        )

    def test_convert_quote_to_invoice_links_both_ways(self):
        invoice = convert_quote_to_invoice(self.quote)
        self.quote.refresh_from_db()
        self.assertEqual(self.quote.status, "converted")
        self.assertEqual(self.quote.converted_invoice_id, invoice.id)
        self.assertEqual(invoice.source_quote.id, self.quote.id)
        self.assertEqual(invoice.status, "draft")
        self.assertTrue(invoice.number.startswith("BR-"))
        self.assertEqual(invoice.client_id, self.client_obj.id)
        self.assertEqual(invoice.project_id, self.project.id)
        self.assertEqual(invoice.amount_ht, Decimal("500.00"))
        # Numéro FAC non consommé tant que brouillon
        issue_invoice(invoice)
        invoice.refresh_from_db()
        self.assertTrue(invoice.number.startswith("FAC-"))

    def test_convert_via_http(self):
        response = self.http.post(f"/factures/devis/{self.quote.id}/convertir/")
        self.assertEqual(response.status_code, 302)
        self.quote.refresh_from_db()
        self.assertEqual(self.quote.status, "converted")


class CreditNoteAndPaymentTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("pay@example.com")
        self.company = _company(user, siren="777777777", name="Pay Co")
        self.http = self.client
        self.http.force_login(user)
        self.invoice = Invoice.objects.create(
            company=self.company,
            number="BR-pay",
            client_name="Client",
            amount_ht=Decimal("100.00"),
            vat_rate=Decimal("20.00"),
            status="draft",
        )
        issue_invoice(self.invoice)
        self.invoice.refresh_from_db()

    def test_partial_then_full_payment(self):
        register_payment(self.invoice, Decimal("50.00"), method="transfer")
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal("50.00"))
        self.assertEqual(self.invoice.amount_remaining, Decimal("70.00"))
        self.assertEqual(self.invoice.status, "issued")
        register_payment(self.invoice, Decimal("70.00"), method="card")
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "paid")
        self.assertEqual(self.invoice.amount_remaining, Decimal("0.00"))

    def test_credit_note_linked_and_issued(self):
        note = CreditNote.objects.create(
            company=self.company,
            number="BR-avo",
            invoice=self.invoice,
            amount_ht=Decimal("20.00"),
            vat_rate=Decimal("20.00"),
            reason="Retour partiel",
            status="draft",
        )
        issue_credit_note(note)
        note.refresh_from_db()
        self.assertTrue(note.number.startswith("AVO-"))
        self.assertEqual(note.status, "issued")
        self.assertEqual(note.invoice_id, self.invoice.id)


class CatalogLineTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("cat@example.com")
        self.company = _company(user, siren="888888888", name="Cat Co")
        self.product = Product.objects.create(
            company=self.company,
            label="Pose fenêtre",
            unit_price=Decimal("250.00"),
            vat_rate=Decimal("20.00"),
        )
        self.invoice = Invoice.objects.create(
            company=self.company,
            number="BR-cat",
            client_name="Client",
            amount_ht=Decimal("250.00"),
            vat_rate=Decimal("20.00"),
            status="draft",
        )

    def test_line_references_catalog(self):
        line = InvoiceLine.objects.create(
            invoice=self.invoice,
            product=self.product,
            description=self.product.label,
            quantity=Decimal("2.000"),
            unit_price=self.product.unit_price,
            vat_rate=self.product.vat_rate,
        )
        self.assertEqual(line.amount_ht, Decimal("500.00"))
        self.assertEqual(line.product_id, self.product.id)
        # Ligne reste éditable indépendamment
        line.unit_price = Decimal("200.00")
        line.save()
        self.assertEqual(line.amount_ht, Decimal("400.00"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.unit_price, Decimal("250.00"))


class PdfImportTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("pdf@example.com")
        self.company = _company(user, siren="999999999", name="PDF Co")
        self.http = self.client
        self.http.force_login(user)

    def _build_pdf(self) -> bytes:
        from documents.pdf import FONT

        pdf = FPDF(format="A4", unit="mm")
        pdf.add_page()
        pdf.add_font("DejaVu", "", str(FONT))
        pdf.set_font("DejaVu", size=12)
        content = (
            "FACTURE FAC-2026-00099\n"
            "Facturé à : Société Dupont SARL\n"
            "SIREN 123456782\n"
            "contact@dupont-exemple.fr\n"
            "Pose de porte 2 x 150.00 TVA 20%\n"
            "Total HT : 300,00 €\n"
            "TVA 20 %\n"
            "Total TTC : 360,00 €\n"
        )
        pdf.multi_cell(0, 8, content)
        return bytes(pdf.output())

    def test_parse_heuristics(self):
        text = (
            "FACTURE N° FAC-2026-42\n"
            "Facturé à : Atelier Martin\n"
            "SIREN 812345679\n"
            "Total HT : 100,00 €\n"
            "TVA 20%\n"
            "Total TTC : 120,00 €\n"
        )
        parsed = parse_invoice_text(text)
        self.assertIn("Martin", parsed["client_name"])
        self.assertEqual(parsed["client_siren"], "812345679")
        self.assertEqual(parsed["amount_ht"], Decimal("100.00"))
        self.assertEqual(parsed["vat_rate"], Decimal("20.00"))

    def test_import_creates_draft_client_and_products(self):
        data = self._build_pdf()
        text = extract_pdf_text(data)
        self.assertTrue(len(text) > 20)
        invoice, parsed = import_invoice_pdf(self.company, data, filename="demo.pdf")
        self.assertEqual(invoice.status, "draft")
        self.assertTrue(invoice.number.startswith("BR-"))
        self.assertIsNotNone(invoice.client_id)
        self.assertTrue(Client.objects.filter(company=self.company).exists())
        self.assertTrue(Product.objects.filter(company=self.company).exists())
        self.assertTrue(invoice.lines.exists())
        # Réimport réutilise le client (SIREN / nom)
        invoice2, _ = import_invoice_pdf(self.company, data, filename="demo2.pdf")
        self.assertEqual(invoice2.client_id, invoice.client_id)
        self.assertEqual(Client.objects.filter(company=self.company).count(), 1)

    def test_scanned_pdf_fails_gracefully(self):
        # PDF minimal sans texte extractible
        empty = (
            b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
        )
        with self.assertRaises(PdfImportError):
            extract_pdf_text(empty)

    def test_import_view(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        data = self._build_pdf()
        upload = SimpleUploadedFile("facture.pdf", data, content_type="application/pdf")
        response = self.http.post("/factures/import-pdf/", {"pdf_file": upload})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Invoice.objects.filter(company=self.company, status="draft").exists())


class CrudPagesSmokeTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("crud@example.com")
        self.company = _company(user, siren="101010101", name="CRUD Co")
        self.http = self.client
        self.http.force_login(user)

    def test_list_pages(self):
        for url in (
            "/factures/",
            "/factures/clients/",
            "/factures/produits/",
            "/factures/projets/",
            "/factures/devis/",
            "/factures/avoirs/",
            "/factures/paiements/",
            "/factures/tickets/",
            "/factures/import-pdf/",
            "/agent/brouillons/",
        ):
            response = self.http.get(url)
            self.assertEqual(response.status_code, 200, url)



class ThemeAndDocumentPdfTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("themes@example.com")
        self.user = user
        self.company = _company(user, siren="919191919", name="Thèmes Co")
        self.http = self.client
        self.http.force_login(user)
        self.invoice = Invoice.objects.create(
            company=self.company,
            number="BR-theme",
            client_name="Client Lignes",
            amount_ht=Decimal("250.00"),
            vat_rate=Decimal("20.00"),
            status="draft",
        )
        InvoiceLine.objects.create(
            invoice=self.invoice,
            position=1,
            description="Prestation catalogue A",
            quantity=Decimal("2"),
            unit_price=Decimal("100.00"),
            vat_rate=Decimal("20.00"),
        )
        InvoiceLine.objects.create(
            invoice=self.invoice,
            position=2,
            description="Prestation catalogue B avec une description assez longue pour le PDF",
            quantity=Decimal("1"),
            unit_price=Decimal("50.00"),
            vat_rate=Decimal("20.00"),
        )

    def test_all_themes_render_pdf_bytes(self):
        from companies.models import INVOICE_THEMES
        from documents.pdf import render_invoice_pdf

        for code, _label in INVOICE_THEMES:
            self.company.invoice_theme = code
            self.company.save(update_fields=["invoice_theme"])
            payload = render_invoice_pdf(self.invoice, self.company)
            self.assertTrue(payload.startswith(b"%PDF"), code)
            self.assertGreater(len(payload), 500, code)

    def test_sheet_shows_invoice_lines(self):
        response = self.http.get(f"/factures/{self.invoice.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Prestation catalogue A")
        self.assertContains(response, "Prestation catalogue B")
        self.assertNotContains(response, "Prestation — Client Lignes")

    def test_legacy_sheet_without_lines(self):
        bare = Invoice.objects.create(
            company=self.company,
            number="BR-legacy",
            client_name="Sans Lignes",
            amount_ht=Decimal("80.00"),
            vat_rate=Decimal("20.00"),
            status="draft",
        )
        response = self.http.get(f"/factures/{bare.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Prestation — Sans Lignes")

    def test_new_themes_accepted_in_settings(self):
        for theme in ("graphite", "indigo", "terra"):
            response = self.http.post("/societe/", {
                "theme": theme,
                "next": "/cockpit/",
            })
            self.assertEqual(response.status_code, 302, theme)
            self.company.refresh_from_db()
            self.assertEqual(self.company.invoice_theme, theme)

    def test_quote_and_credit_pdf_endpoints(self):
        quote = Quote.objects.create(
            company=self.company,
            number="BR-theme-q",
            client_name="Prospect",
            amount_ht=Decimal("100.00"),
            vat_rate=Decimal("20.00"),
            status="draft",
        )
        qpdf = self.http.get(f"/factures/devis/{quote.id}/pdf/")
        self.assertEqual(qpdf.status_code, 200)
        self.assertTrue(qpdf.content.startswith(b"%PDF"))

        issue_invoice(self.invoice)
        self.invoice.refresh_from_db()
        note = CreditNote.objects.create(
            company=self.company,
            invoice=self.invoice,
            number="BR-theme-av",
            amount_ht=Decimal("10.00"),
            vat_rate=Decimal("20.00"),
            status="draft",
        )
        cpdf = self.http.get(f"/factures/avoirs/{note.id}/pdf/")
        self.assertEqual(cpdf.status_code, 200)
        self.assertTrue(cpdf.content.startswith(b"%PDF"))

    def test_quote_credit_pdf_tenant_isolation(self):
        other_user = get_user_model().objects.create_user("other-theme@example.com")
        other = _company(other_user, siren="929292929", name="Autre")
        quote = Quote.objects.create(
            company=other,
            number="BR-iso-q",
            client_name="X",
            amount_ht=Decimal("10.00"),
            vat_rate=Decimal("20.00"),
        )
        inv = Invoice.objects.create(
            company=other,
            number="BR-iso-f",
            client_name="X",
            amount_ht=Decimal("10.00"),
            vat_rate=Decimal("20.00"),
            status="issued",
        )
        note = CreditNote.objects.create(
            company=other,
            invoice=inv,
            number="BR-iso-av",
            amount_ht=Decimal("5.00"),
            vat_rate=Decimal("20.00"),
        )
        self.assertEqual(self.http.get(f"/factures/devis/{quote.id}/pdf/").status_code, 404)
        self.assertEqual(self.http.get(f"/factures/avoirs/{note.id}/pdf/").status_code, 404)



class InvoiceDashboardTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("dash@example.com")
        self.user = user
        self.company = Company.objects.create(
            owner=user,
            siren="834567890",
            denomination="Dash SARL",
            forme="SARL",
            regime="reel_simple",
            tva="reel",
            exercice_debut=date(2026, 1, 1),
            activites=["menuiserie"],
        )
        generate_portal(self.company)
        Invoice.objects.create(
            company=self.company,
            number="FAC-2026-00001",
            client_name="Client A",
            amount_ht=Decimal("100.00"),
            vat_rate=Decimal("20.00"),
            status="issued",
        )
        Invoice.objects.create(
            company=self.company,
            number="BR-draft1",
            client_name="Client B",
            amount_ht=Decimal("50.00"),
            vat_rate=Decimal("20.00"),
            status="draft",
        )

    def test_dashboard_kpis_and_login(self):
        self.client.force_login(self.user)
        r = self.client.get(f"/factures/?societe={self.company.id}")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "CA facturé TTC")
        self.assertContains(r, "120,00")  # 100 HT + 20%
        self.assertContains(r, "À encaisser")
        self.assertContains(r, "Toutes les factures")

    def test_list_still_available(self):
        self.client.force_login(self.user)
        r = self.client.get(f"/factures/liste/?societe={self.company.id}")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "FAC-2026-00001")
        self.assertContains(r, "BR-draft1")



SAMPLE_RECEIPT_TEXT = """
CARREFOUR MARKET
12 rue de la Paix
Paris
Date: 03/11/2026
Eau 50cl                 1,20
Pain                     2,40
TOTAL TTC               45,60 €
TVA 20 %                 7,60
CB
Merci de votre visite
"""


class TicketDeCaisseTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("tickets@example.com")
        self.user = user
        self.company = _company(user, siren="876543210", name="Tickets Co")
        self.http = self.client
        self.http.force_login(user)

    def test_parse_receipt_heuristics(self):
        from .receipt_ocr import parse_receipt_text
        data = parse_receipt_text(SAMPLE_RECEIPT_TEXT)
        self.assertIn("CARREFOUR", data["magasin"].upper())
        self.assertEqual(data["montant_ttc"], Decimal("45.60"))
        self.assertEqual(data["taux_tva"], Decimal("20.00"))
        self.assertTrue(data["moyen_paiement"])
        self.assertEqual(str(data["date"].year), "2026")

    def test_ocr_missing_engine_french_error(self):
        from unittest.mock import patch
        from .receipt_ocr import ReceiptOcrError, ocr_image_bytes
        with patch("documents.receipt_ocr._tesseract_available", return_value=False):
            with self.assertRaises(ReceiptOcrError) as ctx:
                ocr_image_bytes(b"fake", filename="x.jpg")
        self.assertIn("Tesseract", str(ctx.exception))

    def test_upload_with_mocked_ocr_creates_draft_entry(self):
        from unittest.mock import patch
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import TicketDeCaisse
        from accounting.models import JournalEntry

        png = SimpleUploadedFile("ticket.png", b"\x89PNG\r\n\x1a\nfake", content_type="image/png")
        with patch("documents.views.extract_receipt_text", return_value=SAMPLE_RECEIPT_TEXT):
            with patch("documents.views.validate_upload"):
                response = self.http.post(
                    f"/factures/tickets/import/?societe={self.company.id}",
                    {"fichier": png, "categorie": "fournitures"},
                )
        self.assertEqual(response.status_code, 302)
        ticket = TicketDeCaisse.objects.get(company=self.company)
        self.assertEqual(ticket.statut, "brouillon")
        self.assertEqual(ticket.montant_ttc, Decimal("45.60"))
        self.assertEqual(ticket.categorie, "fournitures")
        self.assertTrue(ticket.ocr_text)
        self.assertIsNotNone(ticket.journal_entry_id)
        entry = ticket.journal_entry
        self.assertFalse(entry.validated)
        self.assertTrue(entry.drafted_by_ai)
        debit = sum(line.debit for line in entry.lines.all())
        credit = sum(line.credit for line in entry.lines.all())
        self.assertEqual(debit, credit)
        self.assertEqual(debit, Decimal("45.60"))

    def test_list_filters_and_totals(self):
        from .models import TicketDeCaisse
        TicketDeCaisse.objects.create(
            company=self.company,
            date=date(2026, 11, 1),
            magasin="Total Energies",
            montant_ttc=Decimal("60.00"),
            montant_tva=Decimal("10.00"),
            taux_tva=Decimal("20.00"),
            categorie="carburant",
            statut="brouillon",
        )
        TicketDeCaisse.objects.create(
            company=self.company,
            date=date(2026, 10, 1),
            magasin="Boulangerie",
            montant_ttc=Decimal("12.00"),
            montant_tva=Decimal("1.09"),
            taux_tva=Decimal("10.00"),
            categorie="restauration",
            statut="valide",
        )
        r = self.http.get(
            f"/factures/tickets/?societe={self.company.id}&categorie=carburant"
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Total Energies")
        self.assertNotContains(r, "Boulangerie")
        self.assertContains(r, "60,00")

    def test_dashboard_tickets_card(self):
        from .models import TicketDeCaisse
        TicketDeCaisse.objects.create(
            company=self.company,
            date=date(2026, 11, 2),
            magasin="Station",
            montant_ttc=Decimal("30.00"),
            montant_tva=Decimal("5.00"),
            categorie="carburant",
        )
        r = self.http.get(f"/factures/?societe={self.company.id}")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Tickets de caisse")
        self.assertContains(r, "30,00")

    def test_validate_keeps_entry_unposted(self):
        from .models import TicketDeCaisse
        from .receipt_services import validate_ticket
        ticket = TicketDeCaisse.objects.create(
            company=self.company,
            date=date(2026, 11, 3),
            magasin="Leclerc",
            montant_ttc=Decimal("24.00"),
            montant_tva=Decimal("4.00"),
            taux_tva=Decimal("20.00"),
            categorie="fournitures",
            moyen_paiement="CB",
        )
        entry = validate_ticket(ticket)
        ticket.refresh_from_db()
        self.assertEqual(ticket.statut, "valide")
        self.assertFalse(entry.validated)
        self.assertEqual(entry.lines.count(), 3)  # HT + TVA + crédit

    def test_tenant_isolation(self):
        from .models import TicketDeCaisse
        other_user = get_user_model().objects.create_user("other-tk@example.com")
        other = _company(other_user, siren="111222333", name="Autre")
        ticket = TicketDeCaisse.objects.create(
            company=other,
            date=date(2026, 11, 1),
            magasin="Secret",
            montant_ttc=Decimal("9.00"),
            montant_tva=Decimal("1.50"),
        )
        r = self.http.get(f"/factures/tickets/{ticket.id}/?societe={self.company.id}")
        self.assertEqual(r.status_code, 404)

    def test_wrong_type_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        bad = SimpleUploadedFile("x.txt", b"hello", content_type="text/plain")
        response = self.http.post(
            f"/factures/tickets/import/?societe={self.company.id}",
            {"fichier": bad},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Type de fichier")



class TicketCameraUploadTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("camera@example.com")
        self.user = user
        self.company = _company(user, siren="855555555", name="Camera Co")
        self.http = self.client
        self.http.force_login(user)

    def test_upload_page_has_mobile_camera_capture(self):
        r = self.http.get(f"/factures/tickets/import/?societe={self.company.id}")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Prendre en photo")
        self.assertContains(r, 'data-ticket-camera')
        self.assertContains(r, 'capture="environment"')
        self.assertContains(r, 'accept="image/*"')
        self.assertContains(r, "mobile-only")
        self.assertContains(r, "desktop-only")
        self.assertContains(r, 'data-ticket-upload-form')

    def test_list_has_mobile_camera_entry(self):
        r = self.http.get(f"/factures/tickets/?societe={self.company.id}")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Prendre en photo")
        self.assertContains(r, "camera=1")
        self.assertContains(r, "mobile-only")

    def test_camera_field_goes_through_ocr_flow(self):
        """Le même champ name=fichier (alimenté par la caméra côté JS) passe l'OCR."""
        from unittest.mock import patch
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import TicketDeCaisse

        png = SimpleUploadedFile(
            "camera-shot.jpg",
            b"\xff\xd8\xff\xe0fakejpeg",
            content_type="image/jpeg",
        )
        with patch("documents.views.extract_receipt_text", return_value=SAMPLE_RECEIPT_TEXT):
            with patch("documents.views.validate_upload"):
                response = self.http.post(
                    f"/factures/tickets/import/?societe={self.company.id}",
                    {"fichier": png, "categorie": "carburant"},
                )
        self.assertEqual(response.status_code, 302)
        ticket = TicketDeCaisse.objects.get(company=self.company)
        self.assertEqual(ticket.categorie, "carburant")
        self.assertTrue(ticket.ocr_text)
        self.assertIsNotNone(ticket.journal_entry_id)
        self.assertFalse(ticket.journal_entry.validated)

    def test_heic_rejected_with_french_message(self):
        from .receipt_ocr import ReceiptOcrError, validate_upload
        with self.assertRaises(ReceiptOcrError) as ctx:
            validate_upload("ticket.heic", "image/heic", 120_000)
        self.assertIn("HEIC", str(ctx.exception))

    def test_size_limit_is_10mb(self):
        from .receipt_ocr import MAX_UPLOAD_BYTES, ReceiptOcrError, validate_upload
        self.assertEqual(MAX_UPLOAD_BYTES, 10 * 1024 * 1024)
        with self.assertRaises(ReceiptOcrError) as ctx:
            validate_upload("big.jpg", "image/jpeg", MAX_UPLOAD_BYTES + 1)
        self.assertIn("10 Mo", str(ctx.exception))
