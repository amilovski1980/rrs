# -*- coding: utf-8 -*-
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def main():
    import uuid
    import django
    django.setup()
    from django.test.utils import setup_test_environment
    setup_test_environment()
    from django.contrib.auth import get_user_model
    from django.test import Client, TestCase
    from companies.models import Company
    from accounting.models import ChartAccount, JournalEntry

    t = TestCase()
    c = Client()

    def login_as(email):
        User = get_user_model()
        if not User.objects.filter(email__iexact=email).exists():
            User.objects.create_user(email.lower())
        c.post("/compte/", {"email": email})

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

    email = f"u{uuid.uuid4().hex[:8]}@mamed.fr"
    siren = "".join(str(uuid.uuid4().int)[i] for i in range(9))[:9]
    if not siren.isdigit() or len(siren) != 9:
        siren = str(uuid.uuid4().int % 10**9).zfill(9)
    login_as(email)
    co = add_company(siren, f"Menuiserie {siren[:4]}")
    print("logué commité owner :", co.owner.email, "| co =", co.id)
    assert co.owner.email == email

    r = c.post("/compta/ecriture/nouvelle/", entry_data(co, [
        ("213", "1000.00", ""), ("401", "", "1000.00")]), follow=True)
    assert JournalEntry.objects.filter(company=co).count() == 1, r.status_code
    print("OK écriture équilibrée enregistrée")

    before = JournalEntry.objects.filter(company=co).count()
    r = c.post("/compta/ecriture/nouvelle/", entry_data(co, [
        ("213", "1000.00", ""), ("401", "", "900.00")]), follow=True)
    t.assertContains(r, "équilibrée")
    assert JournalEntry.objects.filter(company=co).count() == before
    print("OK écriture déséquilibrée rejetée")

    r = c.post("/compta/ecriture/nouvelle/", entry_data(co, [
        ("213", "500.00", "500.00"), ("512", "", "")]), follow=True)
    t.assertContains(r, "à la fois")
    print("OK ligne débit+crédit rejetée")

    r = c.get("/compta/grand-livre/?societe=" + str(co.id))
    t.assertEqual(r.status_code, 200)
    t.assertContains(r, "213")
    r = c.get("/compta/balance/?societe=" + str(co.id))
    t.assertEqual(r.status_code, 200)
    t.assertContains(r, "équilibré")
    print("OK grand livre + balance")

    login_as("test2@mamed.fr")
    r = c.get("/compta/grand-livre/?societe=" + str(co.id))
    # Pas de société pour ce compte : le grand livre de l'autre n'est pas affiché.
    assert r.status_code == 302, r.status_code
    assert "/ajouter/" in r["Location"], r["Location"]
    followed = c.get("/compta/grand-livre/?societe=" + str(co.id), follow=True)
    assert "Achat test F-001" not in followed.content.decode()
    print("OK tenant isolation (grand livre d'un autre non affiché)")
    print("TOUS TESTS OK")


if __name__ == "__main__":
    main()
