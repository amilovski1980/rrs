"""Client API Sirene INSEE v3.11.
Doc : https://api.insee.fr/api-sirene/3.11
Auth : cle d'API INSEE_API_KEY (header X-INSEE-Api-Key-Integration),\r
ou OAuth2 client_credentials (INSEE_CLIENT_ID / INSEE_CLIENT_SECRET),\r
ou jeton direct via INSEE_TOKEN (dev / tests).
Fallback : si non configuré, l'app propose la saisie manuelle.

La recherche publique (nom, SIREN, SIRET) passe par l'annuaire
recherche-entreprises.api.gouv.fr, sans clé.
"""
from __future__ import annotations

import hashlib
import logging
import socket
import threading
from contextlib import contextmanager

import httpx
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)
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

ANNUAIRE_HOST = "recherche-entreprises.api.gouv.fr"
ANNUAIRE_SEARCH_URL = f"https://{ANNUAIRE_HOST}/search"
ANNUAIRE_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "RoadRunnerSolutions/1.0 (contact@roadrunner-solutions.fr)",
}
_SEARCH_CACHE_SECONDS = 90
_DNS_LOCK = threading.Lock()


@contextmanager
def _use_ipv4(host: str, ip: str):
    """Force une adresse : certains A records de l'annuaire coupent le TLS."""
    with _DNS_LOCK:
        original = socket.getaddrinfo

        def pinned(query, port, *args, **kwargs):
            if query == host:
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
            return original(query, port, *args, **kwargs)

        socket.getaddrinfo = pinned
        try:
            yield
        finally:
            socket.getaddrinfo = original


def _annuaire_get(params: dict) -> httpx.Response:
    """GET annuaire. En cas de coupure TLS, essaie les autres adresses IPv4."""
    try:
        return httpx.get(
            ANNUAIRE_SEARCH_URL, params=params, headers=ANNUAIRE_HEADERS, timeout=12,
        )
    except httpx.HTTPError as first_error:
        ips: list[str] = []
        try:
            for info in socket.getaddrinfo(ANNUAIRE_HOST, 443, socket.AF_INET, socket.SOCK_STREAM):
                ip = info[4][0]
                if ip not in ips:
                    ips.append(ip)
        except socket.gaierror:
            ips = []
        last_error = first_error
        for ip in ips:
            try:
                with _use_ipv4(ANNUAIRE_HOST, ip):
                    return httpx.get(
                        ANNUAIRE_SEARCH_URL, params=params, headers=ANNUAIRE_HEADERS, timeout=12,
                    )
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("Annuaire entreprises injoignable via %s", ip)
        raise last_error


def parse_company_query(raw: str) -> tuple[str, str]:
    """Classe une saisie : nom, SIREN (9 chiffres) ou SIRET (14 chiffres)."""
    text = " ".join((raw or "").replace("\u00a0", " ").split())
    if not text or len(text) > 80:
        return "invalid", text[:80]
    if all(char.isdigit() or char in " .-/" for char in text):
        digits = "".join(char for char in text if char.isdigit())
        if len(digits) == 9:
            return "siren", digits
        if len(digits) == 14:
            return "siret", digits
        return "invalid", digits or text
    if len(text) < 2:
        return "invalid", text
    return "name", text


def _adresse_from_etablissement(etab: dict | None) -> str:
    if not etab:
        return ""
    adresse = etab.get("geo_adresse") or etab.get("adresse") or ""
    return str(adresse).strip()[:255]


def _etablissement_for(hit: dict, siret: str) -> dict:
    siege = hit.get("siege") or {}
    if not siret:
        return siege
    if str(siege.get("siret") or "") == siret:
        return siege
    for etab in hit.get("matching_etablissements") or []:
        if str(etab.get("siret") or "") == siret:
            return etab
    return siege


def slim_annuaire_hit(hit: dict, *, siret: str = "") -> dict:
    """Fiche courte, sérialisable dans le cookie de session.

    N'embarque pas la réponse brute (dirigeants, finances, etc.).
    """
    etab = _etablissement_for(hit, siret)
    nature = str(hit.get("nature_juridique") or "")
    naf = (
        (etab.get("activite_principale") if etab else None)
        or hit.get("activite_principale")
        or ""
    )
    etat = str(hit.get("etat_administratif") or "")
    return {
        "siren": str(hit.get("siren") or "")[:9],
        "siret": str((etab or {}).get("siret") or siret or "")[:14],
        "denomination": str(
            hit.get("nom_raison_sociale") or hit.get("nom_complet") or ""
        )[:255],
        "forme": LEGAL_FORMS.get(nature, "SARL"),
        "categorie_juridique": nature[:10],
        "adresse": _adresse_from_etablissement(etab),
        "code_naf": str(naf).replace(".", "")[:10],
        "naf": str(naf)[:12],
        "activite_suggeree": activity_from_naf(str(naf)),
        "date_creation": str(hit.get("date_creation") or "")[:10],
        "etat": {"A": "Active", "C": "Cessée"}.get(etat, etat)[:20],
        "tranche_effectifs": str(hit.get("tranche_effectif_salarie") or "")[:8],
    }


def _siren_cache_key(siren: str) -> str:
    return f"annuaire-siren:{siren}"


def search_entreprises(query: str, *, per_page: int = 10) -> tuple[list[dict], str | None]:
    """Recherche nom / SIREN / SIRET sur l'annuaire public.

    Retourne (fiches courtes, code d'erreur). Ne lève pas.
    Codes : None, ``invalid``, ``rate_limit``, ``error``.
    """
    kind, normalized = parse_company_query(query)
    if kind == "invalid":
        return [], "invalid"
    digest = hashlib.sha256(f"{kind}:{normalized.casefold()}".encode()).hexdigest()
    cache_key = f"annuaire-search-{digest}"
    cached = cache.get(cache_key)
    if cached is not None:
        return list(cached), None
    try:
        response = _annuaire_get({
            "q": normalized,
            "per_page": max(1, min(per_page, 25)),
            "page": 1,
        })
    except httpx.HTTPError:
        logger.warning("Annuaire entreprises injoignable pour %s", kind)
        return [], "error"
    if response.status_code == 429:
        logger.warning("Annuaire entreprises : limite de débit (429)")
        return [], "rate_limit"
    if response.status_code >= 400:
        if response is not None:
            logger.warning("Annuaire entreprises : HTTP %s", response.status_code)
        return [], "error"
    try:
        payload = response.json()
    except ValueError:
        return [], "error"
    slim: list[dict] = []
    seen: set[str] = set()
    for hit in payload.get("results") or []:
        if not isinstance(hit, dict):
            continue
        card = slim_annuaire_hit(hit, siret=normalized if kind == "siret" else "")
        if not card["siren"] or not card["denomination"]:
            continue
        if kind == "siren" and card["siren"] != normalized:
            continue
        if kind == "siret" and card["siren"] != normalized[:9]:
            continue
        if card["siren"] in seen:
            continue
        seen.add(card["siren"])
        slim.append(card)
        cache.set(_siren_cache_key(card["siren"]), card, _SEARCH_CACHE_SECONDS)
        if len(slim) >= per_page:
            break
    cache.set(cache_key, slim, _SEARCH_CACHE_SECONDS)
    return slim, None


def official_card(siren: str) -> tuple[dict | None, str | None]:
    """Fiche officielle d'un SIREN, sans JSON brut. Ne lève pas."""
    digits = "".join(char for char in (siren or "") if char.isdigit())
    if len(digits) != 9:
        return None, "invalid"
    cached = cache.get(_siren_cache_key(digits))
    if isinstance(cached, dict) and cached.get("siren") == digits and "denomination" in cached:
        return cached, None
    results, error = search_entreprises(digits)
    if error:
        return None, error
    hit = next((item for item in results if item.get("siren") == digits), None)
    if hit is None:
        return None, "empty"
    return hit, None


def lookup_annuaire(siren: str) -> dict | None:
    """Annuaire public des entreprises, sans clé. Secours quand l'INSEE n'est pas joignable."""
    card, error = official_card(siren)
    if error == "rate_limit":
        raise InseeError("Annuaire entreprises saturé (429).")
    if error == "error":
        raise InseeError("Annuaire entreprises indisponible.")
    return card


def lookup_siren(siren: str) -> tuple[dict | None, str | None]:
    """Retourne (donnees, message d'erreur éventuel). Ne lève jamais.

    La fiche renvoyée ne contient pas la réponse brute : la session Vercel
    est un cookie, trop petit pour le JSON complet de l'API.
    """
    try:
        client = InseeClient()
        if client.api_key or client.direct_token or (client.client_id and client.client_secret):
            data = InseeClient.normalize(client.get_siren(siren))
            data.pop("raw", None)
            if not data.get("siren"):
                data["siren"] = siren
            if data.get("denomination"):
                return data, None
    except InseeNotConfigured:
        pass
    except InseeNotFound:
        return None, "not_found"
    except (InseeError, httpx.HTTPError, ValueError):
        pass
    try:
        data = lookup_annuaire(siren)
    except (InseeError, httpx.HTTPError, ValueError):
        return None, "error"
    if not data or not data.get("denomination"):
        return None, "not_found"
    return data, None

