# -*- coding: utf-8 -*-
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()

from django.test.utils import setup_test_environment
setup_test_environment()
from django.core.mail import outbox
from django.test import Client, TestCase
from companies.models import Company
from accounting.models import ChartAccount, JournalEntry

t = TestCase()
c = Client()


def login_as(email):
    c.post("/compte/", {"email": email})
    url = re.search(r"http://[^\s]+", outbox[-1].body).group()
    c.get(url, follow=True)


def add_company(siren, den, regime="reel_simple", tva="franchise", acts=("btp",)):
    import companies.views as _views
    _views.lookup_siren = lambda s: (
        {
            "siren": s,
            "denomination": den,
            "forme": "SARL",
            "adresse": "",
            "code_naf": "4332A",
            "activite_suggeree": acts[0],
            "raw": {"uniteLegale": {"siren": s}},
        },
        None,
    )
    c.post("/ajouter/", {"siren": siren})
    r = c.post("/ajouter/confirmer/", {
        "denomination": den, "forme": "SARL", "activites": list(acts),
        "regime": regime, "tva": tva, "exercice_debut": "2026-01-01",
    })
    assert r.status_code in (200, 302)
    return Company.objects.get(siren=siren)


def entry_data(co, lines):
    d = {
        "societe": str(co.id),
        "journal": str(co.journals.get(code="BQ").id),
        "date": "2026-01-15",
        "label": "Achat test F-001",
        "reference": "F-001",
        "lines-TOTAL_FORMS": str(len(lines)),
        "lines-INITIAL_FORMS": "0",
        "lines-MIN_NUM_FORMS": "0",
        "lines-MAX_NUM_FORMS": "10",
    }
    for i, (code, debit, credit) in enumerate(lines):
        d[f"lines-{i}-account"] = str(ChartAccount.objects.get(company=co, code=code).id)
        d[f"lines-{i}-debit"] = debit
        d[f"lines-{i}-credit"] = credit
    return d


# 1. Login + société
import uuid
email = f"u{uuid.uuid4().hex[:8]}@mamed.fr"
siren = "".join(str(uuid.uuid4().int)[i] for i in range(9))[:9]
if not siren.isdigit() or len(siren) != 9:
    siren = str(uuid.uuid4().int % 10**9).zfill(9)
login_as(email)
co = add_company(siren, f"Menuiserie {siren[:4]}")
print("logué commité owner :", co.owner.email, "| co =", co.id)
assert co.owner.email == email

# 2. Écriture équilibrée acceptée
r = c.post("/compta/ecriture/nouvelle/", entry_data(co, [
    ("213", "1000.00", ""), ("401", "", "1000.00")]), follow=True)
assert JournalEntry.objects.filter(company=co).count() == 1, r.status_code
print("OK écriture équilibrée enregistrée")

# 3. Écriture déséquilibrée rejetée
before = JournalEntry.objects.filter(company=co).count()
r = c.post("/compta/ecriture/nouvelle/", entry_data(co, [
    ("213", "1000.00", ""), ("401", "", "900.00")]), follow=True)
t.assertContains(r, "équilibrée")
assert JournalEntry.objects.filter(company=co).count() == before
print("OK écriture déséquilibrée rejetée")

# 4. Débit ET crédit sur la même ligne -> rejet
r = c.post("/compta/ecriture/nouvelle/", entry_data(co, [
    ("213", "500.00", "500.00"), ("512", "", "")]), follow=True)
t.assertContains(r, "à la fois")
print("OK ligne débit+crédit rejetée")

# 5. Grand livre + balance
r = c.get("/compta/grand-livre/?societe=" + str(co.id))
t.assertEqual(r.status_code, 200)
t.assertContains(r, "213")
r = c.get("/compta/balance/?societe=" + str(co.id))
t.assertEqual(r.status_code, 200)
t.assertContains(r, "équilibré")
print("OK grand livre + balance")

# 6. Tenant isolation : un autre user ne peut pas lire le grand livre de co
login_as("test2@mamed.fr")
r = c.get("/compta/grand-livre/?societe=" + str(co.id))
assert r.status_code == 404, r.status_code
print("OK tenant isolation (404 pour non-propriétaire)")
print("TOUS TESTS OK")
