# -*- coding: utf-8 -*-
"""Test du parcours SIREN -> INSEE -> validation -> cockpit."""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

FAKE = {
    "siren": "123456789",
    "denomination": "DUPONT MENUISERIE",
    "forme": "SARL",
    "categorie_juridique": "5499",
    "adresse": "12 RUE DES ARTISANS 75011 PARIS",
    "code_naf": "4332A",
    "activite_suggeree": "btp",
    "date_creation": "2018-04-01",
    "etat": "A",
    "tranche_effectifs": "03",
    "raw": {"uniteLegale": {"siren": "123456789"}},
}


def main():
    import django
    django.setup()
    from django.test.utils import setup_test_environment
    setup_test_environment()
    from django.contrib.auth import get_user_model
    from django.test import Client
    from companies.models import Company

    def login(c, email):
        User = get_user_model()
        if not User.objects.filter(email__iexact=email).exists():
            User.objects.create_user(email.lower())
        c.post("/compte/", {"email": email})

    # 1. Normalisation INSEE
    from integrations.insee import InseeClient, activity_from_naf
    raw = {
        "uniteLegale": {
            "siren": "123456789",
            "denominationUniteLegale": "DUPONT MENUISERIE",
            "categorieJuridiqueUniteLegale": "5499",
            "activitePrincipaleUniteLegale": "43.32A",
            "dateCreationUniteLegale": "2018-04-01",
            "etatAdministratifUniteLegale": "A",
        },
        "etablissements": [{
            "etablissementSiege": True,
            "adresseEtablissement": {
                "numeroVoieEtablissement": "12",
                "typeVoieEtablissement": "RUE",
                "libelleVoieEtablissement": "DES ARTISANS",
                "codePostalEtablissement": "75011",
                "libelleCommuneEtablissement": "PARIS",
            },
        }],
    }
    n = InseeClient.normalize(raw)
    assert n["denomination"] == "DUPONT MENUISERIE"
    assert n["forme"] == "SARL"
    assert n["code_naf"] == "4332A"
    assert "PARIS" in n["adresse"]
    assert n["activite_suggeree"] == "btp", n["activite_suggeree"]
    assert activity_from_naf("43.22B") == "plomberie"
    assert activity_from_naf("56.10A") == "resto"
    print("OK normalisation INSEE")

    # 1b. Nouveau format 3.11 : périodes + réponse /siret (siège)
    raw311 = {
        "uniteLegale": {
            "siren": "356000000",
            "dateCreationUniteLegale": "1991-01-01",
            "trancheEffectifsUniteLegale": "53",
            "periodesUniteLegale": [{
                "dateFin": None,
                "etatAdministratifUniteLegale": "A",
                "denominationUniteLegale": "LA POSTE",
                "categorieJuridiqueUniteLegale": "5510",
                "activitePrincipaleNAF25UniteLegale": "53.10Y",
            }],
        },
        "etablissements": [{
            "siret": "35600000000048",
            "etablissementSiege": True,
            "adresseEtablissement": {
                "numeroVoieEtablissement": "9",
                "typeVoieEtablissement": "RUE",
                "libelleVoieEtablissement": "DU COLONEL PIERRE AVIA",
                "codePostalEtablissement": "75015",
                "libelleCommuneEtablissement": "PARIS",
            },
        }],
    }
    n = InseeClient.normalize(raw311)
    assert n["denomination"] == "LA POSTE"
    assert n["forme"] == "SA"
    assert n["code_naf"] == "5310Y"
    assert n["etat"] == "A"
    assert n["adresse"].endswith("75015 PARIS")
    print("OK normalisation format 3.11 (périodes + siège)")

    # 2. Parcours complet avec API simulée
    import companies.views as views
    views.lookup_siren = lambda siren: (dict(FAKE, siren=siren), None)

    siren = str(uuid.uuid4().int % 10**9).zfill(9)
    FAKE["siren"] = siren
    c = Client()
    login(c, f"insee{uuid.uuid4().hex[:6]}@mamed.fr")

    r = c.post("/ajouter/", {"siren": siren})
    assert r.status_code == 302 and r["Location"].endswith("/ajouter/confirmer/"), r.status_code
    r = c.get("/ajouter/confirmer/")
    assert r.status_code == 200
    assert "DUPONT MENUISERIE" in r.content.decode()
    assert "12 RUE DES ARTISANS" in r.content.decode()
    print("OK étape 1 -> confirmation avec données INSEE")

    r = c.post("/ajouter/confirmer/", {
        "denomination": "DUPONT MENUISERIE",
        "forme": "SARL",
        "activites": ["btp"],
        "regime": "reel_simple",
        "tva": "reel",
        "exercice_debut": "2026-01-01",
    })
    assert r.status_code == 302, r.status_code
    co = Company.objects.get(siren=siren)
    assert co.address == "12 RUE DES ARTISANS 75011 PARIS"
    assert co.code_naf == "4332A"
    assert co.source_data["source"] == "insee_sirene"
    assert co.journals.count() == 5
    assert co.accounts.filter(code="44566").exists()
    print("OK création cockpit depuis données INSEE + portail généré")

    # 3. SIREN en double bloqué
    r = c.post("/ajouter/", {"siren": siren})
    assert "déjà dans votre cockpit" in r.content.decode()
    print("OK doublon SIREN bloqué")

    # 4. Fallback quand API non configurée
    views.lookup_siren = lambda siren: (None, "not_configured")
    r = c.post("/ajouter/", {"siren": "987654321"}, follow=True)
    assert r.status_code == 200
    assert "pas encore configurée" in r.content.decode()
    print("OK fallback saisie manuelle")

    # 5. Session absente -> retour étape 1
    c2 = Client()
    login(c2, f"insee{uuid.uuid4().hex[:6]}@mamed.fr")
    r = c2.get("/ajouter/confirmer/")
    assert r.status_code == 302
    print("OK garde-fou session")
    print("TOUS TESTS INSEE OK")


if __name__ == "__main__":
    main()
