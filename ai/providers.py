"""Fournisseur effectif du chat Aminia et réglages vocaux xAI.

La valeur enregistrée dans le back-office prime sur l'environnement.
"""
from __future__ import annotations

import httpx

from django.conf import settings

XAI_CHAT_BASE = "https://api.x.ai/v1"
OLLAMA_DEFAULT_BASE = "http://localhost:11434/v1"
VLLM_DEFAULT_BASE = "http://localhost:8000/v1"


def list_ai_models(base: str, api_key: str = "", timeout: float = 8.0) -> dict:
    """Liste les modèles exposés par une API compatible OpenAI ou Ollama.

    - `{base}/models` (OpenAI, vLLM, Ollama `/v1`, xAI) ;
    - repli natif Ollama `{racine}/api/tags` quand la racine sans `/v1`.
    """
    base = (base or "").strip().rstrip("/")
    if not base:
        raise ValueError("URL de base vide.")
    if not base.lower().startswith(("http://", "https://")):
        raise ValueError("L'URL doit commencer par http:// ou https://.")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    errors: list[str] = []
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        try:
            response = client.get(f"{base}/models", headers=headers)
            if response.status_code == 200:
                data = (response.json() or {}).get("data") or []
                ids = sorted(
                    {
                        entry.get("id")
                        for entry in data
                        if isinstance(entry, dict) and entry.get("id")
                    }
                )
                if ids:
                    return {"models": ids, "source": "openai", "base": base}
                errors.append(f"{base}/models : 200 sans modèle")
            else:
                errors.append(f"{base}/models : HTTP {response.status_code}")
        except Exception as exc:
            errors.append(f"{base}/models : {exc}")

        root = base[: -len("/v1")] if base.endswith("/v1") else base
        try:
            response = client.get(f"{root}/api/tags", headers=headers)
            if response.status_code == 200:
                entries = (response.json() or {}).get("models") or []
                ids = sorted(
                    {
                        entry.get("name")
                        for entry in entries
                        if isinstance(entry, dict) and entry.get("name")
                    }
                )
                if ids:
                    return {"models": ids, "source": "ollama", "base": base}
                errors.append(f"{root}/api/tags : 200 sans modèle")
            else:
                errors.append(f"{root}/api/tags : HTTP {response.status_code}")
        except Exception as exc:
            errors.append(f"{root}/api/tags : {exc}")
    raise ValueError(" ; ".join(errors) or "Aucun modèle trouvé.")


def _config():
    from admin_backoffice.models import SiteConfiguration

    return SiteConfiguration.objects.filter(pk=1).first()


def overlay(env_value: str, db_value: str) -> str:
    db_value = (db_value or "").strip()
    if db_value:
        return db_value
    return (env_value or "").strip()


def text_provider() -> dict:
    config = _config()
    chosen = ""
    if config is not None:
        chosen = (config.ai_text_provider or "").strip()
    if chosen not in ("qwen", "xai", "ollama"):
        chosen = (getattr(settings, "AI_TEXT_PROVIDER", "") or "qwen").strip()
    if chosen not in ("qwen", "xai", "ollama"):
        chosen = "qwen"
    if chosen == "xai":
        key = overlay(getattr(settings, "XAI_API_KEY", ""), getattr(config, "xai_api_key", "") if config else "")
        model = overlay(
            getattr(settings, "XAI_TEXT_MODEL", "") or "grok-3",
            getattr(config, "xai_text_model", "") if config else "",
        ) or "grok-3"
        return {
            "code": "xai",
            "label": "xAI / Grok",
            "base": XAI_CHAT_BASE,
            "key": key,
            "model": model,
            "configured": bool(key and model),
        }
    if chosen == "ollama":
        base = overlay(
            getattr(settings, "OLLAMA_BASE_URL", "") or OLLAMA_DEFAULT_BASE,
            getattr(config, "llm_base_url", "") if config else "",
        )
        key = overlay(getattr(settings, "LLM_API_KEY", ""), getattr(config, "llm_api_key", "") if config else "")
        model = overlay(getattr(settings, "LLM_MODEL", ""), getattr(config, "llm_model", "") if config else "")
        return {
            "code": "ollama",
            "label": "Ollama (local)",
            "base": base,
            "key": key,
            "model": model,
            "configured": bool(base and model),
        }
    base = overlay(getattr(settings, "LLM_BASE_URL", ""), getattr(config, "llm_base_url", "") if config else "")
    key = overlay(getattr(settings, "LLM_API_KEY", ""), getattr(config, "llm_api_key", "") if config else "")
    model = overlay(getattr(settings, "LLM_MODEL", ""), getattr(config, "llm_model", "") if config else "")
    return {
        "code": "qwen",
        "label": "Qwen",
        "base": base,
        "key": key,
        "model": model,
        "configured": bool(base),
    }


def voice_config() -> dict:
    config = _config()
    key = overlay(getattr(settings, "XAI_API_KEY", ""), getattr(config, "xai_api_key", "") if config else "")
    model = overlay(
        getattr(settings, "XAI_VOICE_MODEL", "") or "grok-voice-latest",
        getattr(config, "xai_voice_model", "") if config else "",
    ) or "grok-voice-latest"
    voice = overlay(
        getattr(settings, "XAI_VOICE", "") or "eve",
        getattr(config, "xai_voice", "") if config else "",
    ) or "eve"
    return {"key": key, "model": model, "voice": voice, "configured": bool(key)}
