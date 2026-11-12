"""Fournisseur effectif du chat Aminia et réglages vocaux xAI.

La valeur enregistrée dans le back-office prime sur l'environnement.
"""
from __future__ import annotations

from django.conf import settings

XAI_CHAT_BASE = "https://api.x.ai/v1"


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
    if chosen not in ("qwen", "xai"):
        chosen = (getattr(settings, "AI_TEXT_PROVIDER", "") or "qwen").strip()
    if chosen not in ("qwen", "xai"):
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
