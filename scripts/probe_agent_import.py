# Test E2E : lot + document CSV produits -> agent IA -> analyse stockee.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from ai.providers import text_provider
from companies.models import Company
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from history_import import agent_analysis
from history_import.services import add_upload, create_batch


def main():
    user = get_user_model().objects.filter(email="mobtest@demo.invalid").first()
    company = Company.objects.filter(owner=user).first()
    provider = text_provider()
    print("provider:", provider["label"], "| configure:", provider["configured"])
    if not provider["configured"]:
        print("ARRET: configurez un fournisseur texte dans Reglages IA")
        return

    csv = (
        b"Product;Store;Category;Quantity;Sales amount excluding tax;"
        b"Tax amount;Sales amount including tax\n"
        + "Café Espresso;Boutique Paris;Boissons;10;15.00;1.50;16.50\n".encode("utf-8")
        + "Café Latte;Boutique Paris;Boissons;8;21.60;2.16;23.76\n".encode("utf-8")
    )
    batch = create_batch(company, user, label="TEST agent produits")
    add_upload(batch, SimpleUploadedFile("ventes-produits-test.csv", csv, "text/csv"), user=user)
    document = batch.documents.first()
    print("document:", document.original_name, "| status:", document.status, "| kind:", document.kind)
    data = agent_analysis.agent_analyze_document(document, user=user)
    print("KIND:", data.get("kind"))
    print("explication:", (data.get("explication") or "")[:140])
    document.refresh_from_db()
    print(
        "-> kind:", document.kind,
        "| client:", document.customer_name,
        "| ttc:", document.amount_ttc,
        "| status:", document.status,
    )


main()
