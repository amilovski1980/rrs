from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from fpdf import FPDF

from .models import Company
from .rib_scan import parse_rib_text


class RibParsingTests(SimpleTestCase):
    SAMPLE = (
        "BANQUE CIC ILE-DE-FRANCE\n"
        "IBAN FR76 1027 8060 4100 0206 3428 704\n"
        "BIC CMCIFR2A"
    )

    def test_reads_iban_bic_and_bank(self):
        details = parse_rib_text(self.SAMPLE)
        self.assertEqual(details.iban, "FR76 1027 8060 4100 0206 3428 704")
        self.assertEqual(details.bic, "CMCIFR2A")
        self.assertIn("CIC", details.bank_name)

    def test_tolerates_ocr_spaces(self):
        details = parse_rib_text("IBAN : FR7610278060410002063428704\nBIC:CMCIFR2A")
        self.assertEqual(details.iban, "FR76 1027 8060 4100 0206 3428 704")
        self.assertEqual(details.bic, "CMCIFR2A")

    def test_empty_text_returns_nothing(self):
        self.assertFalse(parse_rib_text("").found)


class BankSettingsTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("banque@exemple.fr")
        self.company = Company.objects.create(
            owner=user,
            siren="812345679",
            denomination="Atelier Banque",
            forme="SARL",
            regime="reel_simple",
            tva="reel",
            exercice_debut=date(2026, 1, 1),
        )
        self.client.force_login(user)

    def test_bank_fields_are_saved_and_formatted(self):
        response = self.client.post("/societe/", {
            "denomination": "Atelier Banque",
            "forme": "SARL",
            "address": "",
            "phone": "",
            "email": "",
            "invoice_theme": "azur",
            "regime": "reel_simple",
            "tva": "reel",
            "bank_name": "CIC Île-de-France",
            "bank_iban": "FR7610278060410002063428704",
            "bank_bic": "cmcifr2a",
        })
        self.assertEqual(response.status_code, 302)
        self.company.refresh_from_db()
        self.assertEqual(self.company.bank_iban, "FR76 1027 8060 4100 0206 3428 704")
        self.assertEqual(self.company.bank_bic, "CMCIFR2A")
        self.assertEqual(self.company.bank_name, "CIC Île-de-France")

    def test_settings_page_offers_rib_scan(self):
        page = self.client.get("/societe/")
        self.assertContains(page, "Coordonnées bancaires")
        self.assertContains(page, "Scanner le RIB")
        self.assertContains(page, 'name="rib_scan"')

    def test_scan_rib_prefills_fields_without_saving(self):
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        pdf.cell(0, 10, "BANQUE CIC ILE-DE-FRANCE", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 10, "IBAN FR76 1027 8060 4100 0206 3428 704", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 10, "BIC CMCIFR2A", new_x="LMARGIN", new_y="NEXT")
        upload = SimpleUploadedFile(
            "rib.pdf", bytes(pdf.output()), content_type="application/pdf"
        )
        response = self.client.post("/societe/", {
            "scan_rib": "1",
            "rib_scan": upload,
            "denomination": "Atelier Banque",
            "forme": "SARL",
            "invoice_theme": "azur",
            "regime": "reel_simple",
            "tva": "reel",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "RIB lu")
        self.assertContains(response, "FR76 1027 8060 4100 0206 3428 704")
        self.assertContains(response, "CMCIFR2A")
        self.company.refresh_from_db()
        self.assertEqual(self.company.bank_iban, "")
