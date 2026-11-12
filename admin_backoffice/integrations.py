"""État des intégrations et test de connexion, sans jamais exposer un secret en clair."""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx
from django.conf import settings

from .sms import mask_secret

logger = logging.getLogger(__name__)

LOCAL_LLM_KEY = "not-needed-for-vllm-local"


def _config():
    from .models import SiteConfiguration

    return SiteConfiguration.objects.filter(pk=1).first()


def _overlay(env_value: str, db_value: str) -> str:
    """La valeur enregistrée dans le back-office prime sur la variable d'environnement."""
    db_value = (db_value or "").strip()
    if db_value:
        return db_value
    return (env_value or "").strip()


def _safe(message, secrets) -> str:
    text = str(message or "")
    for secret in secrets:
        secret = (secret or "").strip()
        if secret and secret != LOCAL_LLM_KEY and len(secret) >= 4:
            text = text.replace(secret, "••••")
    text = " ".join(text.split())
    return text[:180]


def _host(url: str) -> str:
    try:
        netloc = urlparse(url).netloc
    except ValueError:
        netloc = ""
    return netloc or "URL renseignée"


def insee_material():
    config = _config()
    api_key = _overlay(getattr(settings, "INSEE_API_KEY", ""), getattr(config, "insee_api_key", "") if config else "")
    token = (getattr(settings, "INSEE_TOKEN", "") or "").strip()
    client_id = (getattr(settings, "INSEE_CLIENT_ID", "") or "").strip()
    client_secret = (getattr(settings, "INSEE_CLIENT_SECRET", "") or "").strip()
    return {
        "api_key": api_key,
        "token": token,
        "client_id": client_id,
        "client_secret": client_secret,
        "configured": bool(api_key or token or (client_id and client_secret)),
    }


def inpi_token() -> str:
    return (getattr(settings, "INPI_TOKEN", "") or "").strip()


def qwen_material():
    from ai.providers import text_provider

    # Le fournisseur actif peut être xAI : la carte Qwen décrit quand même le déploiement local.
    config = _config()
    base = _overlay(getattr(settings, "LLM_BASE_URL", ""), getattr(config, "llm_base_url", "") if config else "")
    key = _overlay(getattr(settings, "LLM_API_KEY", ""), getattr(config, "llm_api_key", "") if config else "")
    model = _overlay(getattr(settings, "LLM_MODEL", ""), getattr(config, "llm_model", "") if config else "")
    spec = text_provider()
    return {
        "base": base,
        "key": key,
        "model": model,
        "configured": bool(base),
        "active": spec["code"] == "qwen",
    }


def xai_material():
    from ai.providers import text_provider, voice_config

    spoken = voice_config()
    config = _config()
    text_model = _overlay(
        getattr(settings, "XAI_TEXT_MODEL", "") or "grok-3",
        getattr(config, "xai_text_model", "") if config else "",
    ) or "grok-3"
    return {
        "key": spoken["key"],
        "text_model": text_model,
        "voice_model": spoken["model"],
        "voice": spoken["voice"],
        "configured": bool(spoken["key"]),
        "active_chat": text_provider()["code"] == "xai",
    }


def stripe_material():
    from billing.stripe_api import stripe_publishable, stripe_secret, stripe_webhook_secret

    secret = stripe_secret()
    public = stripe_publishable()
    webhook = stripe_webhook_secret()
    return {
        "secret": secret,
        "public": public,
        "webhook": webhook,
        "configured": bool(secret),
    }


def integration_cards() -> list[dict]:
    insee = insee_material()
    if insee["api_key"]:
        insee_detail = "Clé API enregistrée · " + mask_secret(insee["api_key"])
    elif insee["token"]:
        insee_detail = "Jeton enregistré · " + mask_secret(insee["token"])
    elif insee["client_id"] and insee["client_secret"]:
        insee_detail = "Identifiants OAuth enregistrés · " + mask_secret(insee["client_secret"])
    else:
        insee_detail = "Non configurée"

    token = inpi_token()
    qwen = qwen_material()
    if not qwen["configured"]:
        qwen_detail = "Non configurée"
    elif not qwen["key"] or qwen["key"] == LOCAL_LLM_KEY:
        qwen_detail = f"URL {_host(qwen['base'])} · clé non requise (déploiement local)"
    else:
        qwen_detail = f"URL {_host(qwen['base'])} · clé {mask_secret(qwen['key'])}"
    if qwen["model"]:
        qwen_detail += f" · modèle {qwen['model']}"
    if qwen["active"]:
        qwen_detail += " · fournisseur du chat"

    xai = xai_material()
    if xai["configured"]:
        xai_detail = (
            f"Clé {mask_secret(xai['key'])} · chat {xai['text_model']} · "
            f"voix {xai['voice_model']} / {xai['voice']}"
        )
        if xai["active_chat"]:
            xai_detail += " · fournisseur du chat"
    else:
        xai_detail = "Non configurée"

    stripe = stripe_material()
    if stripe["configured"]:
        stripe_detail = "Clé secrète " + mask_secret(stripe["secret"])
        if stripe["public"]:
            stripe_detail += " · clé publique " + mask_secret(stripe["public"])
        if stripe["webhook"]:
            stripe_detail += " · webhook " + mask_secret(stripe["webhook"])
    else:
        stripe_detail = "Non configurée"

    return [
        {
            "code": "insee",
            "name": "INSEE Sirene",
            "description": "Recherche officielle des sociétés par SIREN.",
            "configured": insee["configured"],
            "detail": insee_detail,
            "origin": "INSEE_API_KEY, INSEE_TOKEN ou couple OAuth. Une clé saisie dans les paramètres remplace la variable d'environnement.",
        },
        {
            "code": "inpi",
            "name": "INPI (RNE)",
            "description": "Répertoire national des entreprises.",
            "configured": bool(token),
            "detail": ("Jeton enregistré · " + mask_secret(token)) if token else "Non configurée",
            "origin": "Variable d'environnement INPI_TOKEN. Elle n'est pas modifiable dans cet écran.",
        },
        {
            "code": "annuaire",
            "name": "Annuaire des entreprises",
            "description": "recherche-entreprises.api.gouv.fr, secours public sans clé.",
            "configured": True,
            "detail": "Disponible sans clé",
            "origin": "Service public. Aucun secret n'est stocké.",
        },
        {
            "code": "qwen",
            "name": "IA Qwen (Aminia)",
            "description": "Modèle self-hébergé, API compatible OpenAI.",
            "configured": qwen["configured"],
            "detail": qwen_detail,
            "origin": "LLM_BASE_URL, LLM_MODEL et la clé peuvent être surchargés dans les paramètres. La valeur enregistrée prime.",
        },
        {
            "code": "xai",
            "name": "xAI / Grok",
            "description": "Chat (api.x.ai) et voix temps réel. La clé n'est jamais affichée en entier.",
            "configured": xai["configured"],
            "detail": xai_detail,
            "origin": "XAI_API_KEY, XAI_TEXT_MODEL, XAI_VOICE_MODEL et XAI_VOICE. Une valeur saisie dans les paramètres remplace l'environnement.",
        },
        {
            "code": "stripe",
            "name": "Stripe",
            "description": "Abonnements par carte, en euros.",
            "configured": stripe["configured"],
            "detail": stripe_detail,
            "origin": "STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY et STRIPE_WEBHOOK_SECRET. Une valeur saisie dans les paramètres remplace l'environnement.",
        },
    ]


def probe(code: str) -> dict:
    handlers = {
        "insee": probe_insee,
        "inpi": probe_inpi,
        "annuaire": probe_annuaire,
        "qwen": probe_qwen,
        "xai": probe_xai,
        "stripe": probe_stripe,
    }
    handler = handlers.get(code)
    if handler is None:
        return {"ok": False, "message": "Intégration inconnue."}
    try:
        return handler()
    except Exception:
        logger.exception("Test d'intégration %s", code)
        return {"ok": False, "message": "Test impossible pour le moment."}


def probe_insee() -> dict:
    from integrations.insee import InseeClient, InseeError, InseeNotConfigured, InseeNotFound

    material = insee_material()
    secrets = [material["api_key"], material["token"], material["client_secret"]]
    if not material["configured"]:
        return {"ok": False, "message": "INSEE : non configurée."}
    client = InseeClient()
    # Le client lit django.conf.settings. On aligne la clé effective (base ou écran).
    if material["api_key"]:
        client.api_key = material["api_key"]
    try:
        client.get_siren("552100554")
    except InseeNotFound:
        return {"ok": True, "message": "Connexion INSEE établie."}
    except InseeNotConfigured:
        return {"ok": False, "message": "INSEE : non configurée."}
    except InseeError as exc:
        return {"ok": False, "message": "Échec de la connexion INSEE. " + _safe(exc, secrets)}
    except Exception as exc:
        return {"ok": False, "message": "Échec de la connexion INSEE. " + _safe(exc, secrets)}
    return {"ok": True, "message": "Connexion INSEE établie."}


def probe_inpi() -> dict:
    from integrations.inpi import InpiClient

    token = inpi_token()
    if not token:
        return {"ok": False, "message": "INPI : non configurée."}
    client = InpiClient(token=token)
    try:
        client.get_company("552100554")
    except ValueError:
        return {"ok": False, "message": "INPI : requête de test refusée."}
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (401, 403):
            return {"ok": False, "message": "INPI : authentification refusée."}
        if status == 404:
            return {"ok": True, "message": "Connexion INPI établie."}
        return {"ok": False, "message": f"INPI : réponse HTTP {status}."}
    except httpx.HTTPError:
        return {"ok": False, "message": "INPI : service injoignable."}
    except Exception as exc:
        return {"ok": False, "message": "Échec de la connexion INPI. " + _safe(exc, [token])}
    return {"ok": True, "message": "Connexion INPI établie."}


def probe_annuaire() -> dict:
    try:
        response = httpx.get(
            "https://recherche-entreprises.api.gouv.fr/search",
            params={"q": "552100554", "per_page": 1},
            headers={"Accept": "application/json"},
            timeout=8,
        )
    except httpx.HTTPError:
        return {"ok": False, "message": "Annuaire des entreprises : service injoignable."}
    if response.status_code == 200:
        return {"ok": True, "message": "Annuaire des entreprises joignable."}
    return {"ok": False, "message": f"Annuaire des entreprises : réponse HTTP {response.status_code}."}


def probe_qwen() -> dict:
    material = qwen_material()
    if not material["configured"]:
        return {"ok": False, "message": "Qwen : non configuré."}
    headers = {"Accept": "application/json"}
    if material["key"] and material["key"] != LOCAL_LLM_KEY:
        headers["Authorization"] = f"Bearer {material['key']}"
    url = material["base"].rstrip("/") + "/models"
    try:
        response = httpx.get(url, headers=headers, timeout=8)
    except httpx.HTTPError:
        return {"ok": False, "message": "Qwen : service injoignable."}
    if response.status_code == 200:
        return {"ok": True, "message": "Connexion Qwen établie."}
    if response.status_code in (401, 403):
        return {"ok": False, "message": "Qwen : authentification refusée."}
    return {"ok": False, "message": f"Qwen : réponse HTTP {response.status_code}."}


def probe_xai() -> dict:
    material = xai_material()
    if not material["configured"]:
        return {"ok": False, "message": "xAI : non configuré."}
    try:
        response = httpx.get(
            "https://api.x.ai/v1/models",
            headers={"Authorization": f"Bearer {material['key']}", "Accept": "application/json"},
            timeout=8,
        )
    except httpx.HTTPError:
        return {"ok": False, "message": "xAI : service injoignable."}
    if response.status_code == 200:
        return {"ok": True, "message": "Connexion xAI établie."}
    if response.status_code in (401, 403):
        return {"ok": False, "message": "xAI : authentification refusée."}
    return {"ok": False, "message": f"xAI : réponse HTTP {response.status_code}."}


def probe_stripe() -> dict:
    from billing.stripe_api import probe_balance

    return probe_balance()
