"""Client API Sirene INSEE v3.11.
Doc : https://api.insee.fr/api-sirene/3.11
Auth : cle d'API INSEE_API_KEY (header X-INSEE-Api-Key-Integration),\r
ou OAuth2 client_credentials (INSEE_CLIENT_ID / INSEE_CLIENT_SECRET),\r
ou jeton direct via INSEE_TOKEN (dev / tests).
Fallback : si non configuré, l'app propose la saisie manuelle.
"""
from __future__ import annotations
import httpx
from django.conf import settings
from django.core.cache import cache
TOKEN_CACHE_KEY = "insee_sirene_token"
TOKEN_URL = "https://api.insee.fr/token"

class InseeError(Exception):
    pass

class InseeNotConfigured(InseeError):
    pass

class InseeNotFound(InseeError):
    pass

# Codes catégorie juridique INSEE -> forme affichée
LEGAL_FORMS = {
    "5499": "SARL",
    "5498": "EURL",
    "5710": "SAS",
    "5720": "SASU",
    "1000": "EI",
    "2110": "EI",
    "6540": "SCI",
    "6599": "SCI",
    "5308": "SELARL",
    "5510": "SA",
    "5800": "SAS",
    "5785": "SASU",
    "5485": "SARL",
}
ACTIVITY_BY_NAF_PREFIX = [
    ("4321", "electricite"),
    ("4322", "plomberie"),
    ("43", "btp"),
    ("41", "btp"),
    ("96.02", "coiffure"),
    ("5602", "coiffure"),
    ("56", "resto"),
]

def activity_from_naf(naf: str | None) -> str:
    """Devine une activité du questionnaire depuis le code NAF."""
    if not naf:
        return "artisan_autre"
    cleaned = naf.replace(".", "").upper()
    for prefix, activity in ACTIVITY_BY_NAF_PREFIX:
        if cleaned.startswith(prefix.replace(".", "")):
            return activity
    return "artisan_autre"

class InseeClient:
    base_url = "https://api.insee.fr/api-sirene/3.11"
    def __init__(self):
        self.api_key = getattr(settings, "INSEE_API_KEY", "")
        self.client_id = getattr(settings, "INSEE_CLIENT_ID", "")
        self.client_secret = getattr(settings, "INSEE_CLIENT_SECRET", "")
        self.direct_token = getattr(settings, "INSEE_TOKEN", "")
    def _headers(self) -> dict:
        # Nouveau portail INSEE : clé d'API dans X-INSEE-Api-Key-Integration.
        if self.api_key:
            return {
                "X-INSEE-Api-Key-Integration": self.api_key,
                "Accept": "application/json",
            }
        return {
            "Authorization": f"Bearer {self._token()}",
            "Accept": "application/json",
        }
    def _token(self) -> str:
        if self.direct_token:
            return self.direct_token
        if not (self.client_id and self.client_secret):
            raise InseeNotConfigured(
                "API Sirene non configurée (INSEE_API_KEY ou INSEE_CLIENT_ID/SECRET)."
            )
        token = cache.get(TOKEN_CACHE_KEY)
        if token:
            return token
        r = httpx.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(self.client_id, self.client_secret),
            timeout=15,
        )
        if r.status_code >= 400:
            raise InseeError(f"Échec d'authentification INSEE ({r.status_code}).")
        token = r.json().get("access_token")
        if not token:
            raise InseeError("Réponse INSEE sans access_token.")
        cache.set(TOKEN_CACHE_KEY, token, timeout=3000)
        return token
    def get_siren(self, siren: str) -> dict:
        if not siren or len(siren) != 9 or not siren.isdigit():
            raise ValueError("SIREN invalide (9 chiffres attendus).")
        # 1) Établissement siège : contient l'adresse + uniteLegale à jour.
        r = httpx.get(
            f"{self.base_url}/siret",
            params={"q": f"siren:{siren} AND etablissementSiege:true"},
            headers=self._headers(),
            timeout=20,
        )
        if r.status_code == 200:
            etabs = r.json().get("etablissements") or []
            if etabs:
                return {"uniteLegale": etabs[0].get("uniteLegale") or {}, "etablissements": etabs}
        # 2) Repli : fiche unité légale (sans adresse).
        r = httpx.get(
            f"{self.base_url}/siren/{siren}",
            headers=self._headers(),
            timeout=20,
        )
        if r.status_code == 404:
            raise InseeNotFound("SIREN introuvable dans la base Sirene.")
        if r.status_code >= 400:
            raise InseeError(f"API Sirene indisponible ({r.status_code}).")
        return r.json()

    # --- Normalisation vers le modèle Company ---
    @staticmethod
    def normalize(raw: dict) -> dict:
        etabs = raw.get("etablissements") or []
        siege = next(
            (e for e in etabs if e.get("etablissementSiege") is True), None
        ) or (etabs[0] if etabs else {})
        adr = siege.get("adresseEtablissement") or {}
        unite = raw.get("uniteLegale") or siege.get("uniteLegale") or {}

        # API 3.11 : les données d'état civil sont dans la période courante.
        periods = unite.get("periodesUniteLegale") or []
        period = next((p for p in periods if not p.get("dateFin")), periods[0] if periods else {})

        denomination = (
            unite.get("denominationUniteLegale")
            or period.get("denominationUniteLegale")
            or " ".join(filter(None, [
                period.get("prenom1UniteLegale") or unite.get("prenom1UniteLegale"),
                period.get("nomUniteLegale") or unite.get("nomUniteLegale"),
            ]))
        )

        naf = (
            unite.get("activitePrincipaleUniteLegale")
            or period.get("activitePrincipaleUniteLegale")
            or unite.get("activitePrincipaleNAF25UniteLegale")
            or period.get("activitePrincipaleNAF25UniteLegale")
        )
        categorie = str(
            period.get("categorieJuridiqueUniteLegale")
            or unite.get("categorieJuridiqueUniteLegale")
            or ""
        )

        address = " ".join(
            filter(None, [
                adr.get("numeroVoieEtablissement"),
                adr.get("typeVoieEtablissement"),
                adr.get("libelleVoieEtablissement"),
                adr.get("codePostalEtablissement"),
                adr.get("libelleCommuneEtablissement"),
            ])
        )

        return {
            "siren": unite.get("siren") or siege.get("siret", "")[:9],
            "denomination": denomination or "",
            "forme": LEGAL_FORMS.get(categorie, "SARL"),
            "categorie_juridique": categorie,
            "adresse": address,
            "code_naf": (naf or "").replace(".", ""),
            "activite_suggeree": activity_from_naf(naf),
            "date_creation": unite.get("dateCreationUniteLegale"),
            "etat": period.get("etatAdministratifUniteLegale") or unite.get("etatAdministratifUniteLegale"),
            "tranche_effectifs": unite.get("trancheEffectifsUniteLegale"),
            "raw": raw,
        }

def lookup_siren(siren: str) -> tuple[dict | None, str | None]:
    """Retourne (donnees, message d'erreur éventuel). Ne lève jamais."""
    try:
        raw = InseeClient().get_siren(siren)
        data = InseeClient.normalize(raw)
        if not data.get("siren"):
            data["siren"] = siren
        return data, None
    except InseeNotConfigured:
        return None, "not_configured"
    except InseeNotFound:
        return None, "not_found"
    except (InseeError, httpx.HTTPError, ValueError):
        return None, "error"

