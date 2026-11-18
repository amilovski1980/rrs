"""Tests des relevés bancaires CSV réels (format CIC)."""
import datetime
import decimal
from datetime import date

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from banking.models import BankTransaction
from companies.models import Company
from history_import.services import (
    add_upload,
    apply_tabular,
    create_batch,
    process_batch,
)

CIC_CSV = (
    "Mois,Date,Valeur,Libelle,Debit,Credit\n"
    'Juillet,01/07/2026,01/07/2026,"REMISE CB /01/07 R55030 CT3686372801 BT 1044,20E COM 4,19E",,1040.01\n'
    "Juillet,01/07/2026,01/07/2026,VIR RECU 0195932555S DE: PLUXEE FRANCE,,226.36\n"
    'Juillet,01/07/2026,01/07/2026,"PRELEVEMENT EUROPEEN 7805813005 DE: ADEME",408.29,\n'
    "Juillet,02/07/2026,01/07/2026,ABONNEMENT MATERIEL TPE,40.50,\n"
    "Juillet,02/07/2026,02/07/2026,CARTE X3189 01/07 METRO,180.63,\n"
)


class BankStatementCsvTests(TestCase):
    def setUp(self):
        user = User.objects.create_user("cic@example.com")
        self.user = user
        self.company = Company.objects.create(
            owner=user,
            siren="811223344",
            denomination="CIC Test SARL",
            forme="SARL",
            regime="reel_simple",
            tva="reel",
            exercice_debut=date(2026, 1, 1),
        )
        self.company.company = self.company
        self.client.force_login(user)

    def _upload_csv(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        batch = create_batch(self.company, self.user, kind_hint="csv")
        add_upload(
            batch,
            SimpleUploadedFile("cic.csv", CIC_CSV.encode("utf-8"), content_type="text/csv"),
            user=self.user,
        )
        return batch.documents.get()

    def test_cic_format_is_detected_and_applied(self):
        document = self._upload_csv()
        process_batch(document.batch, user=self.user)
        document.refresh_from_db()
        self.assertEqual(document.kind, "bank_statement")
        self.assertEqual(document.status, "ready")
        totals = (document.extracted or {}).get("totals") or {}
        self.assertEqual(totals["count"], 5)
        self.assertEqual(document.extracted["rows"][0][0], "01/07/2026")
        self.assertIn("REMISE CB", document.extracted["rows"][0][1])
        self.assertEqual(document.extracted["rows"][0][3], "1040.01")
        self.assertEqual(document.extracted["rows"][2][2], "408.29")

        summary = apply_tabular(document)
        self.assertEqual(summary["created"], 5)
        self.assertEqual(BankTransaction.objects.filter(company=self.company).count(), 5)
        remise = BankTransaction.objects.get(
            company=self.company, label__icontains="REMISE CB /01/07 R55030"
        )
        self.assertEqual(remise.date, datetime.date(2026, 7, 1))
        self.assertEqual(str(remise.amount), "1040.01")
        self.assertTrue(remise.amount > 0)
        prelev = BankTransaction.objects.get(
            company=self.company, label__icontains="ADEME"
        )
        self.assertEqual(str(prelev.amount), "-408.29")
        self.assertTrue(prelev.amount < 0)

    def test_apply_is_idempotent(self):
        document = self._upload_csv()
        process_batch(document.batch, user=self.user)
        document.refresh_from_db()
        self.assertEqual(document.kind, "bank_statement")
        apply_tabular(document)
        apply_tabular(document)
        self.assertEqual(BankTransaction.objects.filter(company=self.company).count(), 5)

    def test_bank_statement_not_accepted_by_generic_import_button(self):
        document = self._upload_csv()
        process_batch(document.batch, user=self.user)
        document.refresh_from_db()
        response = self.client.post(
            reverse("history_import:document_import", args=[document.pk]),
            {"societe": self.company.id},
        )
        self.assertRedirects(
            response,
            reverse("history_import:document", args=[document.pk]),
        )
        content = self.client.get(
            reverse("history_import:document", args=[document.pk])
            + f"?societe={self.company.id}"
        ).content.decode()
        # L'écran propose bien l'application bancaire (pas d'« import » facture générique).
        self.assertIn("Relevé bancaire détecté", content)
        self.assertIn("Créer les opérations bancaires", content)
        self.assertNotIn("Importer ce document", content)
