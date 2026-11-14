from datetime import date
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase

from accounting.models import JournalEntry
from accounting.services import generate_portal
from companies.models import Company
from contacts.models import Contact
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


class ClientLookupFormTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("clients@example.com")
        self.company = _company(user, siren="777777777", name="Clients Co")
        self.http = self.client
        self.http.force_login(user)

    def test_create_form_exposes_automatic_siren_or_name_lookup(self):
        response = self.http.get("/factures/clients/nouveau/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-client-lookup")
        self.assertContains(response, "data-client-lookup-input")
        self.assertContains(response, "data-client-lookup-submit")
        self.assertContains(response, "Rechercher une entreprise")
        self.assertContains(response, 'id="id_siren"')

    def test_dark_create_form_has_the_same_lookup(self):
        response = self.http.get("/dark/factures/clients/nouveau/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-client-lookup")
        self.assertContains(response, "data-client-lookup-input")
        self.assertContains(response, "Rechercher une entreprise")
        self.assertContains(response, 'id="id_siren"')
        self.assertContains(response, "dark-app.css")

    def test_manual_client_creation_still_works(self):
        response = self.http.post("/factures/clients/nouveau/", {
            "name": "Client Manuel",
            "siren": "123456789",
            "address": "1 rue de la Paix, 75002 Paris",
            "email": "",
            "phone": "",
            "notes": "",
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Client.objects.filter(company=self.company, name="Client Manuel").exists())


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



class VatIntracomTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("tva@example.com")
        self.company = _company(user, siren="812345679", name="TVA Co")
        self.client.force_login(user)

    def test_company_vat_number_is_derived_from_siren_when_empty(self):
        self.assertEqual(self.company.tva_intra, "")
        self.assertEqual(self.company.tva_intra_number, "FR28812345679")
        self.company.tva_intra = "fr 28 812 345 679"
        self.company.save(update_fields=["tva_intra"])
        self.assertEqual(self.company.tva_intra_number, "FR28812345679")

    def test_client_form_stores_intracom_identity(self):
        from .forms import ClientForm

        form = ClientForm(
            data={
                "name": "Bau GmbH",
                "siren": "",
                "tva_intra": "de 811 234 567",
                "legal_form": "GmbH",
                "rcs": "HRB 12345",
                "address": "Musterstrasse 1, Berlin",
                "email": "",
                "phone": "",
                "notes": "",
            },
            company=self.company,
        )
        self.assertTrue(form.is_valid(), form.errors)
        client = form.save(commit=False)
        client.company = self.company
        client.save()
        self.assertEqual(client.tva_intra, "DE811234567")
        self.assertEqual(client.legal_form, "GmbH")

    def test_reverse_charge_invoice_forces_zero_vat_and_prints_mention(self):
        from .forms import InvoiceForm
        from .pdf import render_invoice_pdf

        client = Client.objects.create(
            company=self.company,
            name="Bau GmbH",
            tva_intra="DE811234567",
            address="Musterstrasse 1, Berlin",
            legal_form="GmbH",
        )
        form = InvoiceForm(
            data={
                "client": client.pk,
                "client_name": "Bau GmbH",
                "client_siren": "",
                "client_tva_intra": "DE811234567",
                "project": "",
                "amount_ht": "100.00",
                "vat_rate": "20.00",
                "reverse_charge": "on",
                "vat_exemption_reason": "",
            },
            company=self.company,
        )
        self.assertTrue(form.is_valid(), form.errors)
        invoice = form.save(commit=False)
        invoice.company = self.company
        invoice.status = "draft"
        invoice.number = "BR-tva"
        invoice.save()

        self.assertTrue(invoice.reverse_charge)
        self.assertEqual(invoice.vat_rate, Decimal("0.00"))
        self.assertEqual(invoice.vat_amount, Decimal("0.00"))
        self.assertEqual(invoice.amount_ttc, Decimal("100.00"))
        self.assertIn("283-2", invoice.vat_exemption_reason)

        text = extract_pdf_text(render_invoice_pdf(invoice, self.company))
        self.assertIn("Autoliquidation", text)
        self.assertIn("TVA intracommunautaire : DE811234567", text)
        self.assertIn("TVA 0 % (autoliquidation)", text)
        self.assertNotIn("TVA 20 %", text)

    def test_reverse_charge_posts_no_collected_vat(self):
        from .services import issue_invoice

        invoice = Invoice.objects.create(
            company=self.company,
            number="BR-tva-2",
            client_name="Bau GmbH",
            amount_ht=Decimal("100.00"),
            vat_rate=Decimal("0.00"),
            reverse_charge=True,
            status="draft",
        )
        issue_invoice(invoice)
        invoice.refresh_from_db()
        entry = JournalEntry.objects.get(reference=invoice.number)
        self.assertFalse(entry.lines.filter(account__code="44571").exists())
        self.assertEqual(sum(line.debit for line in entry.lines.all()), Decimal("100.00"))


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

    def test_invoice_pdf_matches_reference_layout(self):
        from documents.pdf import render_invoice_pdf

        client = Client.objects.create(
            company=self.company,
            name="WASH & TEINTE",
            siren="907825327",
            address="2 Allée de Chantereine – 78711 Mantes-la-Ville – France",
        )
        self.company.source_data = {"siret": "91919191900017"}
        self.company.slogan = "Stratégie. Performance. Succès."
        self.company.save(update_fields=["source_data", "slogan"])
        self.invoice.client = client
        self.invoice.client_name = "WASH & TEINTE"
        self.invoice.client_siren = "907825327"
        self.invoice.save(update_fields=["client", "client_name", "client_siren"])

        text = extract_pdf_text(render_invoice_pdf(self.invoice, self.company))
        for expected in (
            "FACTURE",
            "BR-theme",
            "FACTURÉ À",
            "WASH & TEINTE",
            "SIREN 907825327",
            "CLI-WASH-TEINTE",
            "DESCRIPTION",
            "QTÉ",
            "UNITÉ",
            "PRIX HT",
            "TVA",
            "TTC",
            "Sous-total HT",
            "TVA 20 %",
            "Montant Total TTC (EUR)",
            "Montant à payer (EUR)",
            "Règlement à 30 jours.",
            "SIRET 919 191 919 00017",
            "Stratégie. Performance. Succès.",
        ):
            self.assertIn(expected, text, expected)

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

    def test_parse_multiple_vat_rates_and_breakdown(self):
        from .receipt_ocr import parse_receipt_text

        text = """
        BRICOMARCHE
        Date: 04/11/2026
        TOTAL TTC               120,00
        TVA 20 %                 10,00
        TVA 10 %                  5,00
        CB
        """
        data = parse_receipt_text(text)
        self.assertEqual(data["montant_ttc"], Decimal("120.00"))
        self.assertEqual(data["montant_tva"], Decimal("15.00"))
        self.assertEqual(data["taux_tva"], Decimal("20.00"))
        self.assertEqual(len(data["vat_breakdown"]), 2)

    def test_scanned_pdf_falls_back_to_embedded_image_ocr(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from .receipt_ocr import extract_pdf_text_or_ocr

        page = SimpleNamespace(
            extract_text=lambda: "",
            images=[SimpleNamespace(data=b"fake-image", name="scan.jpg")],
        )
        reader = SimpleNamespace(pages=[page])
        with patch("pypdf.PdfReader", return_value=reader):
            with patch(
                "documents.receipt_ocr.ocr_image_bytes",
                return_value="BOULANGERIE\nTOTAL TTC 12,00\nTVA 10 % 1,09",
            ):
                text = extract_pdf_text_or_ocr(b"%PDF-fake")
        self.assertIn("BOULANGERIE", text)
        self.assertIn("TOTAL TTC 12,00", text)

    def test_upload_warns_when_a_duplicate_ticket_exists(self):
        from unittest.mock import patch
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import TicketDeCaisse

        TicketDeCaisse.objects.create(
            company=self.company,
            date=date(2026, 11, 3),
            magasin="CARREFOUR MARKET",
            montant_ttc=Decimal("45.60"),
            montant_tva=Decimal("7.60"),
            taux_tva=Decimal("20.00"),
            categorie="fournitures",
        )
        png = SimpleUploadedFile(
            "ticket.png", b"\x89PNG\r\n\x1a\nfake", content_type="image/png"
        )
        with patch("documents.views.extract_receipt_text", return_value=SAMPLE_RECEIPT_TEXT):
            with patch("documents.views.validate_upload"):
                response = self.http.post(
                    f"/factures/tickets/import/?societe={self.company.id}",
                    {"fichier": png, "categorie": "fournitures"},
                    follow=True,
                )
        self.assertContains(response, "Doublon possible")
        self.assertEqual(TicketDeCaisse.objects.filter(company=self.company).count(), 2)

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

    def test_upload_keeps_the_image_in_database_when_storage_is_read_only(self):
        """Vercel monte /var/task en lecture seule : l'image doit aller en base."""
        from unittest.mock import patch

        from django.core.files.storage.filesystem import FileSystemStorage
        from django.core.files.uploadedfile import SimpleUploadedFile

        from .models import TicketDeCaisse

        png_bytes = b"\x89PNG\r\n\x1a\nfake"
        png = SimpleUploadedFile("ticket.png", png_bytes, content_type="image/png")
        with patch("documents.views.extract_receipt_text", return_value=SAMPLE_RECEIPT_TEXT):
            with patch("documents.views.validate_upload"):
                with patch.object(
                    FileSystemStorage,
                    "_save",
                    side_effect=OSError(30, "Read-only file system"),
                ):
                    response = self.http.post(
                        f"/factures/tickets/import/?societe={self.company.id}",
                        {"fichier": png, "categorie": "fournitures"},
                    )
        self.assertEqual(response.status_code, 302)
        ticket = TicketDeCaisse.objects.get(company=self.company)
        self.assertEqual(bytes(ticket.image_data), png_bytes)
        self.assertEqual(ticket.image_type, "image/png")
        self.assertFalse(ticket.image)
        image = self.http.get(
            f"/factures/tickets/{ticket.id}/image/?societe={self.company.id}"
        )
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.content, png_bytes)
        self.assertEqual(image["Content-Type"], "image/png")

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
        self.assertContains(r, 'data-ticket-upload-form')
        self.assertContains(r, "ticket-upload-form")
        self.assertContains(r, 'id="id_fichier"', count=1)
        self.assertContains(r, 'name="fichier"', count=1)

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


class InvoiceThemePreviewCssTests(TestCase):
    """Les miniatures indigo/graphite (et tous les thèmes) ont des règles CSS visibles."""

    def test_app_css_defines_every_invoice_theme_preview(self):
        from pathlib import Path

        from companies.models import INVOICE_THEMES

        css = (Path(__file__).resolve().parents[1] / "static" / "css" / "app.css").read_text()
        for code, _label in INVOICE_THEMES:
            self.assertIn(f".model-{code}", css, f"règle manquante pour {code}")
        # Contraste indigo : bandeau violet + barres non grises par défaut
        self.assertIn(".model-indigo .mp-top", css)
        self.assertIn("background: #4f46e5", css)
        self.assertIn(".model-indigo .mp-row", css)
        self.assertIn("#a5b4fc", css)
        # Graphite : barres claires sur fond sombre
        self.assertIn(".model-graphite .mp-row", css)
        self.assertIn("#64748b", css)
        self.assertIn(".model-graphite .mp-logo", css)

class InvoiceThemeSettingsPageTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("themes@exemple.fr")
        self.company = _company(user, siren="899999999", name="Themes Co")
        self.client.force_login(user)

    def test_settings_page_renders_theme_previews(self):
        from companies.models import INVOICE_THEMES
        page = self.client.get("/societe/")
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        for code, label in INVOICE_THEMES:
            self.assertIn(f"model-{code}", body)
            self.assertIn(label, body)


class TicketDeCaisseFormUxTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("ticketform@example.com")
        self.user = user
        self.company = _company(user, siren="866666666", name="Form Co")
        self.http = self.client
        self.http.force_login(user)

    def test_create_form_renders_sections_labels_and_camera(self):
        r = self.http.get(f"/factures/tickets/nouveau/?societe={self.company.id}")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        for label in (
            "Justificatif",
            "Informations",
            "Montants",
            "Classement",
            "Notes",
            "Date du ticket",
            "Magasin / fournisseur",
            "Montant TTC",
            "Montant TVA",
            "Taux de TVA",
            "Catégorie",
            "Moyen de paiement",
            "Statut",
            "Prendre en photo",
        ):
            self.assertIn(label, body)
        self.assertIn('data-ticket-form', body)
        self.assertIn('data-ticket-form-camera', body)
        self.assertIn('capture="environment"', body)
        self.assertIn('data-ticket-ht', body)
        self.assertIn('aria-required="true"', body)
        self.assertIn('inputmode="decimal"', body)
        self.assertIn('type="date"', body)
        # Required markers
        self.assertIn('class="req"', body)

    def test_validation_errors_show_summary_and_inline(self):
        r = self.http.post(
            f"/factures/tickets/nouveau/?societe={self.company.id}",
            {
                # date manquante, montant invalide
                "magasin": "Test",
                "montant_ttc": "",
                "categorie": "autre",
                "taux_tva": "20",
                "montant_tva": "0",
                "statut": "brouillon",
            },
        )
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("ticket-form-errors", body)
        self.assertIn("Veuillez corriger les erreurs", body)
        self.assertIn("aria-invalid", body)
        self.assertIn("has-error", body)
        self.assertIn("form-error", body)

    def test_edit_form_keeps_existing_values(self):
        from .models import TicketDeCaisse
        ticket = TicketDeCaisse.objects.create(
            company=self.company,
            date=date(2026, 11, 4),
            magasin="Fnac",
            montant_ttc=Decimal("19.99"),
            montant_tva=Decimal("3.33"),
            taux_tva=Decimal("20.00"),
            categorie="fournitures",
            statut="brouillon",
        )
        r = self.http.get(
            f"/factures/tickets/{ticket.id}/modifier/?societe={self.company.id}"
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Fnac")
        self.assertContains(r, "19.99")
        self.assertContains(r, "Justificatif")
        self.assertContains(r, "Enregistrer les modifications")

    def test_ocr_flow_still_works_with_mocked_ocr(self):
        from unittest.mock import patch
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import TicketDeCaisse

        png = SimpleUploadedFile(
            "ocr.png", b"\x89PNG\r\n\x1a\nfake", content_type="image/png"
        )
        with patch("documents.views.extract_receipt_text", return_value=SAMPLE_RECEIPT_TEXT):
            with patch("documents.views.validate_upload"):
                response = self.http.post(
                    f"/factures/tickets/import/?societe={self.company.id}",
                    {"fichier": png, "categorie": "restauration"},
                )
        self.assertEqual(response.status_code, 302)
        ticket = TicketDeCaisse.objects.get(company=self.company)
        self.assertEqual(ticket.statut, "brouillon")
        self.assertEqual(ticket.categorie, "restauration")
        self.assertTrue(ticket.ocr_text)


class DocumentPdfExportTests(TestCase):
    """Export PDF : accès connecté, droit du forfait et URL sombre."""

    def setUp(self):
        from billing.catalog import BOOL_FEATURES
        from billing.models import Plan

        self.user = get_user_model().objects.create_user("pdf@example.com")
        self.company = _company(self.user, siren="912345678", name="Atelier PDF")
        self.invoice = Invoice.objects.create(
            company=self.company,
            number="FAC/2026 001",
            client_name="Client PDF",
            amount_ht=Decimal("100.00"),
            vat_rate=Decimal("20.00"),
            status="issued",
        )
        self.quote = Quote.objects.create(
            company=self.company,
            number="DEV-2026-001",
            client_name="Client PDF",
            amount_ht=Decimal("80.00"),
            vat_rate=Decimal("20.00"),
        )
        self.credit_note = CreditNote.objects.create(
            company=self.company,
            invoice=self.invoice,
            number="AV-2026-001",
            amount_ht=Decimal("20.00"),
            vat_rate=Decimal("20.00"),
        )
        self.plan = Plan.objects.create(
            code="micro-pdf",
            name="Micro PDF",
            price_eur=19,
            entitlements={
                **{key: True for key, _label in BOOL_FEATURES},
                "custom": True,
                "invoice_pdf": False,
                "themes": ["azur"],
            },
        )

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(f"/factures/{self.invoice.id}/pdf/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/compte/", response["Location"])

    def test_forfait_without_pdf_entitlement_gets_403(self):
        from billing.models import Subscription

        Subscription.objects.create(user=self.user, plan=self.plan, status="active")
        self.client.force_login(self.user)
        for url in (
            f"/factures/{self.invoice.id}/pdf/",
            f"/factures/devis/{self.quote.id}/pdf/",
            f"/factures/avoirs/{self.credit_note.id}/pdf/",
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403, f"{url} -> {response.get('Location')}")

    def test_pdf_success_and_safe_filename(self):
        self.client.force_login(self.user)
        response = self.client.get(f"/factures/{self.invoice.id}/pdf/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn("FAC2026_001.pdf", response["Content-Disposition"])

    def test_quote_and_credit_note_pdfs(self):
        self.client.force_login(self.user)
        for url, filename in (
            (f"/factures/devis/{self.quote.id}/pdf/", "DEV-2026-001.pdf"),
            (f"/factures/avoirs/{self.credit_note.id}/pdf/", "AV-2026-001.pdf"),
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            self.assertTrue(response.content.startswith(b"%PDF"), url)
            self.assertIn(filename, response["Content-Disposition"])

    def test_dark_prefixed_pdf_url(self):
        self.client.force_login(self.user)
        response = self.client.get(f"/dark/factures/{self.invoice.id}/pdf/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn("FAC2026_001.pdf", response["Content-Disposition"])

class DocumentEmailTests(TestCase):
    """Envoi des documents : contact principal, signature et PDF joint."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "camille@example.com", password="password123"
        )
        self.user.first_name = "Camille"
        self.user.last_name = "Martin"
        self.user.job_title = "Dirigeante"
        self.user.save(update_fields=["first_name", "last_name", "job_title"])
        self.company = _company(self.user, siren="812345678", name="Atelier Email")
        self.company.phone = "01 23 45 67 89"
        self.company.save(update_fields=["phone"])
        self.customer = Client.objects.create(
            company=self.company,
            name="Cadres Industries",
            siren="552100554",
            email="fiche@example.fr",
        )
        self.contact = Contact.objects.create(
            company=self.company,
            client=self.customer,
            first_name="Alice",
            last_name="Durand",
            department="facturation",
            email="alice@example.fr",
            is_primary=True,
        )
        self.invoice = Invoice.objects.create(
            company=self.company,
            number="FAC-2026-00042",
            client=self.customer,
            client_name="Cadres Industries",
            client_siren="552100554",
            amount_ht=Decimal("100.00"),
            vat_rate=Decimal("20.00"),
            status="issued",
        )
        self.quote = Quote.objects.create(
            company=self.company,
            number="DEV-2026-001",
            client=self.customer,
            client_name="Cadres Industries",
            client_siren="552100554",
            amount_ht=Decimal("100.00"),
            vat_rate=Decimal("20.00"),
            status="sent",
        )
        self.credit_note = CreditNote.objects.create(
            company=self.company,
            invoice=self.invoice,
            number="AV-2026-001",
            amount_ht=Decimal("20.00"),
            vat_rate="20.00",
        )
        self.http = self.client
        self.http.force_login(self.user)

    def test_invoice_email_uses_primary_contact_and_signature(self):
        response = self.http.post(f"/factures/{self.invoice.id}/envoyer/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["alice@example.fr"])
        self.assertIn("Votre facture FAC-2026-00042", message.subject)
        self.assertIn("Alice Durand", message.body)
        self.assertIn("Camille Martin", message.body)
        self.assertIn("Dirigeante", message.body)
        self.assertIn("Atelier Email", message.body)
        self.assertIn("120,00 € TTC", message.body)
        attachments = message.attachments
        self.assertEqual(len(attachments), 1)
        filename, payload, mimetype = attachments[0]
        self.assertEqual(filename, "FAC-2026-00042.pdf")
        self.assertEqual(mimetype, "application/pdf")
        self.assertTrue(payload.startswith(b"%PDF"))

    def test_quote_and_credit_note_are_emailed_with_pdf(self):
        quote_response = self.http.post(f"/factures/devis/{self.quote.id}/envoyer/")
        self.assertEqual(quote_response.status_code, 302)
        note_response = self.http.post(f"/factures/avoirs/{self.credit_note.id}/envoyer/")
        self.assertEqual(note_response.status_code, 302)
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("Votre devis DEV-2026-001", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].attachments[0][0], "DEV-2026-001.pdf")
        self.assertIn("Votre avoir AV-2026-001", mail.outbox[1].subject)
        self.assertEqual(mail.outbox[1].attachments[0][0], "AV-2026-001.pdf")

    def test_dark_email_url_stays_in_dark_space(self):
        response = self.http.post(f"/dark/factures/{self.invoice.id}/envoyer/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/dark/factures/"))
        self.assertEqual(len(mail.outbox), 1)

    def test_missing_client_email_is_reported_without_sending(self):
        client = Client.objects.create(
            company=self.company, name="Sans Email", siren="552100556"
        )
        invoice = Invoice.objects.create(
            company=self.company,
            number="FAC-2026-00043",
            client=client,
            client_name="Sans Email",
            amount_ht=Decimal("50.00"),
            vat_rate="20.00",
            status="issued",
        )
        response = self.http.post(f"/factures/{invoice.id}/envoyer/", follow=True)
        self.assertContains(response, "Aucune adresse email")
        self.assertEqual(len(mail.outbox), 0)

    def test_email_respects_pdf_entitlement(self):
        from billing.catalog import BOOL_FEATURES
        from billing.models import Plan, Subscription

        plan = Plan.objects.create(
            code="micro-email",
            name="Micro Email",
            price_eur=19,
            entitlements={
                **{key: True for key, _label in BOOL_FEATURES},
                "custom": True,
                "invoice_pdf": False,
                "themes": ["azur"],
            },
        )
        Subscription.objects.create(user=self.user, plan=plan, status="active")
        response = self.http.post(f"/factures/{self.invoice.id}/envoyer/")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)


class EInvoicingTests(TestCase):
    """Factur-X : XML CII, PDF joint, dépôt API et garde-fous."""

    def setUp(self):
        from admin_backoffice.models import SiteConfiguration

        self.user = get_user_model().objects.create_user(
            "facturx@example.com", password="password123"
        )
        self.company = _company(self.user, siren="812345679", name="Atelier Factur-X")
        self.company.tva_intra = "FR28812345679"
        self.company.save(update_fields=["tva_intra"])
        self.customer = Client.objects.create(
            company=self.company,
            name="Berlin Handels GmbH",
            siren="",
            tva_intra="DE811234567",
            address="5 Unter den Linden, 10117 Berlin",
        )
        self.invoice = Invoice.objects.create(
            company=self.company,
            number="FAC-2026-00901",
            client=self.customer,
            client_name="Berlin Handels GmbH",
            client_tva_intra="DE811234567",
            amount_ht=Decimal("100.00"),
            vat_rate=Decimal("20.00"),
            reverse_charge=True,
            status="issued",
        )
        self.config, _ = SiteConfiguration.objects.get_or_create(pk=1)
        self.config.einvoicing_enabled = True
        self.config.einvoicing_provider = "generic"
        self.config.einvoicing_api_url = "https://plateforme.example/api/factures"
        self.config.einvoicing_api_key = "secret-plateforme-123"
        self.config.einvoicing_sender_siret = "81234567900011"
        self.config.save()
        self.http = self.client
        self.http.force_login(self.user)

    def test_facturx_xml_contains_reverse_charge_and_parties(self):
        from xml.etree import ElementTree

        from .einvoicing import build_facturx_xml

        payload = build_facturx_xml(self.invoice, self.company, profile="EN16931")
        root = ElementTree.fromstring(payload)
        ns = {
            "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
            "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
        }
        self.assertEqual(
            root.findtext("rsm:ExchangedDocument/ram:ID", namespaces=ns),
            "FAC-2026-00901",
        )
        self.assertEqual(
            root.findtext(
                "rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID",
                namespaces=ns,
            ),
            "urn:cen.eu:en16931:2017",
        )
        self.assertEqual(
            root.findtext(
                ".//ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax/ram:CategoryCode",
                namespaces=ns,
            ),
            "AE",
        )
        tax_total = root.find(
            ".//ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:TaxTotalAmount",
            namespaces=ns,
        )
        self.assertEqual(tax_total.text, "0.00")
        self.assertEqual(tax_total.attrib.get("currencyID"), "EUR")
        seller_vat = root.findtext(
            ".//ram:SellerTradeParty/ram:SpecifiedTaxRegistration/ram:ID", namespaces=ns
        )
        self.assertEqual(seller_vat, "FR28812345679")
        buyer_vat = root.findtext(
            ".//ram:BuyerTradeParty/ram:SpecifiedTaxRegistration/ram:ID", namespaces=ns
        )
        self.assertEqual(buyer_vat, "DE811234567")

    def test_facturx_pdf_embeds_xml_attachment(self):
        from pypdf import PdfReader

        from .einvoicing import build_facturx_pdf

        payload = build_facturx_pdf(self.invoice, self.company)
        self.assertTrue(payload.startswith(b"%PDF"))
        reader = PdfReader(BytesIO(payload))
        self.assertIn("factur-x.xml", reader.attachments)
        self.assertIn(b"CrossIndustryInvoice", reader.attachments["factur-x.xml"][0])

    def test_generate_xml_download_and_submit(self):
        from unittest.mock import Mock, patch

        from .models import EInvoicingSubmission

        generated = self.http.post(
            f"/factures/{self.invoice.id}/facture-electronique/generer/",
            {"profile": "EXTENDED"},
        )
        self.assertEqual(generated.status_code, 302)
        submission = EInvoicingSubmission.objects.get(invoice=self.invoice)
        self.assertEqual(submission.profile, "EXTENDED")
        self.assertEqual(len(submission.checksum), 64)
        page = self.http.get(f"/factures/{self.invoice.id}/facture-electronique/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Dernier dépôt")
        self.assertContains(page, "Télécharger le PDF Factur-X")

        xml_response = self.http.get(
            f"/factures/{self.invoice.id}/facture-electronique/xml/"
        )
        self.assertEqual(xml_response.status_code, 200)
        self.assertIn(b"CrossIndustryInvoice", xml_response.content)

        remote = Mock()
        remote.is_success = True
        remote.status_code = 202
        remote.text = '{"id": "PLAT-42", "status": "accepted"}'
        with patch("documents.einvoicing.httpx.post", return_value=remote) as posted:
            response = self.http.post(
                f"/factures/{self.invoice.id}/facture-electronique/transmettre/"
            )
        self.assertEqual(response.status_code, 302)
        submission.refresh_from_db()
        self.assertEqual(submission.status, "accepted")
        self.assertEqual(submission.remote_id, "PLAT-42")
        self.assertEqual(submission.platform, "generic")
        self.assertIsNotNone(submission.sent_at)
        _, kwargs = posted.call_args
        self.assertEqual(
            kwargs["headers"]["Authorization"], "Bearer secret-plateforme-123"
        )
        self.assertEqual(kwargs["data"]["sender_siret"], "81234567900011")
        self.assertEqual(
            kwargs["files"]["file"][0],
            "factur-x.xml",
        )

    def test_submit_is_refused_when_module_is_disabled(self):
        from .models import EInvoicingSubmission

        submission = EInvoicingSubmission.objects.create(
            invoice=self.invoice,
            profile="EN16931",
            status="generated",
            reference="FE-TEST",
            xml_payload="<xml/>",
            checksum="0" * 64,
        )
        self.config.einvoicing_enabled = False
        self.config.save(update_fields=["einvoicing_enabled"])
        response = self.http.post(
            f"/factures/{self.invoice.id}/facture-electronique/transmettre/",
            follow=True,
        )
        self.assertContains(response, "pas activ")
        submission.refresh_from_db()
        self.assertEqual(submission.status, "generated")
