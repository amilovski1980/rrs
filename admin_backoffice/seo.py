"""SEO & Google Search Console : accès API et agent IA.

Authentification service account sans google-auth : JWT RS256 signé avec
cryptography (déjà installé), échangé contre un token OAuth2, puis appel de
l'API Search Console (lecture des analytics).
"""
from __future__ import annotations

import base64
import json
import time
from datetime import date, timedelta

import httpx

TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"


class SeoError(RuntimeError):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _config_values(config) -> tuple[str, str, str]:
    site = (getattr(config, "seo_gsc_site", "") or "").strip()
    email = (getattr(config, "seo_service_email", "") or "").strip()
    key = (getattr(config, "seo_private_key", "") or "").strip()
    if not (site and email and key):
        raise SeoError(
            "Search Console n'est pas configurée : renseignez la propriété, "
            "l'e-mail du compte de service et sa clé privée, puis Enregistrer."
        )
    return site, email, key


def _access_token(config) -> str:
    _, email, private_key = _config_values(config)
    key = private_key.replace("\\n", "\n")
    if "BEGIN PRIVATE KEY" not in key:
        raise SeoError(
            "La clé privée ne ressemble pas à une clé PEM. Copiez la valeur "
            "'private_key' du fichier JSON du compte de service (avec BEGIN/END PRIVATE KEY)."
        )
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    now = int(time.time())
    header = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = _b64(json.dumps({
        "iss": email,
        "scope": SCOPE,
        "aud": TOKEN_URL,
        "iat": now,
        "exp": now + 3600,
    }).encode())
    signing_input = f"{header}.{claims}".encode()
    try:
        signing_key = serialization.load_pem_private_key(key.encode(), password=None)
    except Exception as exc:
        raise SeoError(f"Clé privée illisible : {exc}") from exc
    signature = signing_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    assertion = signing_input.decode() + "." + _b64(signature)

    response = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        },
        timeout=20.0,
    )
    if response.status_code >= 400:
        detail = ""
        try:
            detail = response.json().get("error_description") or response.json().get("error", "")
        except Exception:
            detail = response.text[:200]
        raise SeoError(
            "Google a refusé l'authentification (" + str(response.status_code) + ") : " + str(detail)
        )
    return response.json()["access_token"]


def fetch_search_analytics(config, days: int = 28, dimension: str = "query") -> list[dict]:
    """Top requêtes (dimension=query) ou pages (dimension=page) sur la période."""
    site, _, _ = _config_values(config)
    token = _access_token(config)
    end = date.today() - timedelta(days=2)  # GSC a 2 jours de latence
    start = end - timedelta(days=max(days, 1))
    payload = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": [dimension],
        "rowLimit": 25,
    }
    from urllib.parse import quote

    response = httpx.post(
        "https://www.googleapis.com/webmasters/v3/sites/"
        + quote(site, safe="")
        + "/searchAnalytics/query",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=25.0,
    )
    if response.status_code >= 400:
        hint = ""
        if response.status_code == 403:
            hint = (
                " Ajoutez l'e-mail du compte de service comme utilisateur de la "
                "propriété dans Search Console (Paramètres → Utilisateurs)."
            )
        raise SeoError(
            f"Search Console a répondu {response.status_code}.{hint} "
            + response.text[:200]
        )
    rows = response.json().get("rows") or []
    return [
        {
            "label": row["keys"][0],
            "clicks": row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
            "ctr": round((row.get("ctr") or 0) * 100, 1),
            "position": round(row.get("position") or 0, 1),
        }
        for row in rows
    ]


def ask_seo_agent(question: str, analytics: list[dict] | None = None, dimension: str = "query") -> str:
    """Interroge l'agent IA (fournisseur LLM configuré) avec les analytics en contexte."""
    from ai.providers import text_provider

    provider = text_provider()
    if not provider or not provider.get("configured"):
        raise SeoError(
            "Aucun agent IA configuré : renseignez l'URL, la clé et le modèle "
            "dans Réglages IA pour que l'agent SEO puisse répondre."
        )
    lines = []
    for row in (analytics or [])[:20]:
        lines.append(
            f"- {row['label']} : {row['clicks']} clics, {row['impressions']} impressions, "
            f"CTR {row['ctr']} %, position {row['position']}"
        )
    context = "\n".join(lines) or "(aucune donnée Search Console disponible pour l'instant)"
    system = (
        "Tu es l'agent SEO de Road Runner Solutions (facturation pour artisans et TPE, "
        "site rrsolutions.io). Tu réponds en français, de façon concrète et actionnable : "
        "titres et meta descriptions proposés, mots-clés à viser, pages à créer, "
        "corrections techniques, plan de « boost » sur 30 jours. "
        "Tu t'appuies sur les données Search Console fournies quand elles existent."
    )
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                f"Données Search Console ({dimension}, 28 jours) :\n{context}\n\n"
                f"Demande : {question}"
            ),
        },
    ]
    try:
        response = httpx.post(
            provider["base"].rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {provider['key']}"} if provider.get("key") else {},
            json={"model": provider["model"], "temperature": 0.4, "messages": messages},
            timeout=60.0,
        )
    except Exception as exc:
        raise SeoError(f"Agent IA injoignable : {exc}") from exc
    if response.status_code >= 400:
        raise SeoError(f"Agent IA : erreur HTTP {response.status_code}.")
    try:
        payload = response.json()
        return (payload["choices"][0]["message"]["content"] or "").strip()
    except Exception as exc:
        raise SeoError(f"Réponse de l'agent illisible : {exc}") from exc
