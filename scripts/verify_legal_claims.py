# Verification de rendu : promesses veridiques, voix livree, Factur-X natif,
# mentions legales corrigees, page d'aide sans placeholder, facture emise verrouillee.
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.contrib.auth import get_user_model
from django.test import Client

from companies.models import Company
from documents.models import Invoice

user = get_user_model().objects.get(email="mobtest@demo.invalid")
company = Company.objects.filter(owner=user).first()
http = Client()
http.force_login(user)

checks = []


def check(label, condition):
    checks.append((label, bool(condition)))
    print(("OK  " if condition else "FAIL") + " " + label)


landing = http.get("/").content.decode("utf-8", "replace")
check("landing: Factur-X natif", "Factur-X natif" in landing)
check("landing: voix dans l'app", "Aminia vous écoute et répond à la voix" in landing)
check("landing: plus de 'prochainement'", "prochainement" not in landing)
check("landing: plus de 'conformes 2026'", "conformes 2026" not in landing)
check("landing: Voix Aminia dans les forfaits", "Voix Aminia" in landing)
check("landing: pas de 'bientôt' voix", "Voix Aminia (bientôt" not in landing)

dark = http.get("/dark/").content.decode("utf-8", "replace")
check("dark: Factur-X natif", "Factur-X natif" in dark)
check("dark: voix livree", "Aminia écoute et répond à la voix" in dark)
check("dark: plus de 'pas encore branchée'", "pas encore branchée" not in dark)

legal = http.get("/mentions-legales/").content.decode("utf-8", "replace")
check("legal: TVA corrigee", "FR32951386127" in legal)
check("legal: ancienne TVA absente", "FR17100408517" not in legal)
check("legal: Vercel cite", "Vercel Inc." in legal)
check("legal: lien Vercel propre", "vercel.comoud" not in legal)

help_page = http.get("/aide/").content.decode("utf-8", "replace")
check("aide: email de support", "contact@roadrunner-solutions.fr" in help_page)
check("aide: plus de placeholder", "À compléter par le propriétaire" not in help_page)

invoice = Invoice.objects.create(
    company=company,
    number="BR-verif-%s" % uuid.uuid4().hex[:8],
    client_name="Client Verif",
    amount_ht="100.00",
    vat_rate="20.00",
    status="draft",
)
invoice.lines.create(description="Prestation", quantity="1", unit_price="100.00", vat_rate="20.00")
invoice.status = "issued"
invoice.save(update_fields=["status"])
invoice.refresh_from_db()
detail = http.get("/factures/%s/" % invoice.id).content.decode("utf-8", "replace")
check("facture emise: statut", invoice.status != "draft")
check("facture emise: pas de lien Modifier", "/modifier/" not in detail)
check("facture emise: mention avoir", "correction par avoir" in detail)
edit = http.get("/factures/%s/modifier/" % invoice.id)
check("facture emise: edition refusee", edit.status_code == 302)

facturx = http.get("/factures/%s/facture-electronique/" % invoice.id)
check("facture electronique: page 200", facturx.status_code == 200)
check(
    "facture electronique: Factur-X",
    "Factur-X" in facturx.content.decode("utf-8", "replace"),
)

invoice.delete()

failed = [label for label, ok in checks if not ok]
print("")
print("TOTAL", len(checks), "| ECHECS", len(failed))
for label in failed:
    print(" -", label)
sys.exit(1 if failed else 0)
