import httpx
from django.conf import settings

# INPI RNE : data.inpi.fr (compte API Entreprise nécessaire)
# https://www.inpi.fr/fr/rne-repertoire-national-des-entreprises
BASE_URL = "https://api.data.inpi.fr/search"


class InpiClient:
    """Récupère le réextrait RNE (ex-KBIS) par SIREN. Pré-remplissage, pas de source
    de vérité legal. Coût ~0,012 EUR par appel, quota payant."""

    def __init__(self, token: str | None = None):
        self.token = token or getattr(settings, "INPI_TOKEN", None)

    @property
    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def get_company(self, siren: str) -> dict | None:
        if not siren or len(siren) != 9 or not siren.isdigit():
            raise ValueError("SIREN invalide (9 chiffres)")

        r = httpx.get(
            BASE_URL,
            params={"filter": f"siren:{siren}"},
            headers=self._headers,
            timeout=10,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
        matches = data.get("total_hits") and data.get("results", [])
        if not matches:
            return None
        return self.normalize(matches[0])

    @staticmethod
    def normalize(raw: dict) -> dict:
        """Normalise le champ INPI -> company data."""
        imprint = (raw.get("immeuble") or {}).get("attributes") or {}
        return {
            "siren": raw.get("siren"),
            "denomination": raw.get("denomination") or raw.get("name"),
            "forme": raw.get("legalForm", {}).get("shortLabel") if raw.get("legalForm") else "SARL",
            "adresse": ", ".join(
                str(x)
                for x in [
                    imprint.get("number"), imprint.get("type"), imprint.get("voie"),
                    imprint.get("codePostal"), imprint.get("commune"),
                ]
                if x
            ),
            "code_naf": raw.get("activitePrincipale", {}).get("codeNaf")
            if raw.get("activitePrincipale")
            else "",
            "raw": raw,
        }


def create_company_from_siren(user, siren: str):
    """Helper: appelle INPI + stocke source_data brute (versionnée)."""
    from companies.models import Company

    data = InpiClient().get_company(siren)
    if not data:
        return None
    company = Company.objects.create(
        owner=user,
        siren=siren,
        denomination=data["denomination"] or f"Société {siren}",
        forme=data.get("forme") or "SARL",
        address=data.get("adresse") or "",
        code_naf=data.get("code_naf") or "",
        source_data={"source": "inpi_rne", "fetched_at": None, "raw": data["raw"]},
    )
    return company
