"""Fournisseur effectif du chat Aminia et réglages vocaux xAI.

La valeur enregistrée dans le back-office prime sur l'environnement.
"""
from __future__ import annotations

import httpx

from django.conf import settings

XAI_CHAT_BASE = "https://api.x.ai/v1"
OLLAMA_DEFAULT_BASE = "http://localhost:11434/v1"
VLLM_DEFAULT_BASE = "http://localhost:8000/v1"


PROBE_TOOL = {
    "type": "function",
    "function": {
        "name": "create_entry_draft",
        "description": "Propose une écriture comptable à valider (journal, comptes, montant).",
        "parameters": {
            "type": "object",
            "properties": {
                "label": {"type": "string", "description": "Libellé de l'opération"},
                "amount": {"type": "number", "description": "Montant TTC en euros"},
            },
            "required": ["label", "amount"],
        },
    },
}


def normalize_chat_base(base: str) -> str:
    """URL de chat effective : ajoute /v1 si l'utilisateur a donné la racine."""
    base = (base or "").strip().rstrip("/")
    if not base or base.endswith("/v1"):
        return base
    return base + "/v1"


def _extract_model_ids(payload) -> list[str]:
    models = []
    for entry in payload or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("id") or entry.get("name") or entry.get("model") or ""
        name = (name or "").strip()
        if name:
            models.append(name)
    return sorted(set(models))


def list_ai_models(base: str, api_key: str = "", timeout: float = 10.0) -> dict:
    """Liste les modèles exposés par une API compatible OpenAI ou Ollama.

    Essaie, dans l'ordre : `{base}/models` (OpenAI), `{base}/v1/models` quand la
    racine a été donnée sans /v1, puis `{racine}/api/tags` (Ollama natif).
    Renvoie aussi la base de chat à utiliser (`chat_base`).
    """
    base = (base or "").strip().rstrip("/")
    if not base:
        raise ValueError("URL de base vide.")
    if not base.lower().startswith(("http://", "https://")):
        raise ValueError("L'URL doit commencer par http:// ou https://.")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    chat_base = normalize_chat_base(base)
    root = base[: -len("/v1")] if base.endswith("/v1") else base
    candidates = [
        (f"{chat_base}/models", "openai", chat_base),
        (f"{root}/models", "openai", base if base.endswith("/v1") else chat_base),
        (f"{root}/api/tags", "ollama", chat_base),
    ]
    errors: list[str] = []
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for url, source, working_base in candidates:
            try:
                response = client.get(url, headers=headers)
                if response.status_code == 200:
                    payload = response.json()
                    if source == "ollama":
                        payload = (payload or {}).get("models") or []
                    else:
                        payload = (payload or {}).get("data") or []
                    models = _extract_model_ids(payload)
                    if models:
                        return {
                            "models": models,
                            "source": source,
                            "base": working_base,
                            "chat_base": working_base,
                        }
                    errors.append(f"{url} : 200 sans modèle")
                else:
                    errors.append(f"{url} : HTTP {response.status_code}")
            except Exception as exc:
                errors.append(f"{url} : {exc}")
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
            "base": normalize_chat_base(base),
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
        "base": normalize_chat_base(base) if base else base,
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


ELEVENLABS_BASE = "https://api.elevenlabs.io"

# Voix xAI du realtime, par genre (surchargeable librement dans la clé).
XAI_VOICES = {"femme": "eve", "homme": "ara"}

# Voix publiques ElevenLabs par genre, utilisées si l'ID n'est pas surchargé.
ELEVENLABS_VOICES = {
    "femme": "21m00Tcm4TlvDq8tWv",  # Rachel
    "homme": "onwK4e9ZLuTAKqWW03F9",  # Daniel
}


def _overlay_field(config, db_attr: str, env_name: str) -> str:
    db_value = (getattr(config, db_attr, "") or "").strip() if config else ""
    if db_value:
        return db_value
    return (getattr(settings, env_name, "") or "").strip()


def voice_agent_config() -> dict:
    """Voix effective pour la lecture des réponses (ElevenLabs ou xAI)."""
    config = _config()
    provider = (getattr(config, "voice_provider", "") or "elevenlabs") if config else "elevenlabs"
    gender = (getattr(config, "voice_gender", "") or "femme") if config else "femme"

    if provider == "elevenlabs":
        key = _overlay_field(config, "elevenlabs_api_key", "ELEVENLABS_API_KEY")
        voice_id = (
            (getattr(config, "elevenlabs_voice_male", "") or "") if gender == "homme"
            else (getattr(config, "elevenlabs_voice_female", "") or "")
        ).strip()
        if not voice_id:
            voice_id = ELEVENLABS_VOICES.get(gender, ELEVENLABS_VOICES["femme"])
        model = _overlay_field(config, "elevenlabs_model", "ELEVENLABS_MODEL") or "eleven_flash_v2_5"
        return {
            "provider": "elevenlabs", "key": key, "voice_id": voice_id,
            "model": model, "gender": gender,
            "configured": bool(key and voice_id),
        }

    key = _overlay_field(config, "xai_api_key", "XAI_API_KEY")
    default_voice = XAI_VOICES.get(gender, XAI_VOICES["femme"])
    voice = _overlay_field(config, "xai_voice", "XAI_VOICE") or default_voice
    model = _overlay_field(config, "xai_voice_model", "XAI_VOICE_MODEL") or "grok-voice-latest"
    return {
        "provider": "xai", "key": key,
        "voice_id": voice,  # xAI : le nom de la voix
        "model": model, "gender": gender,
        "configured": bool(key),
    }


def elevenlabs_tts(text: str, *, api_key: str, voice_id: str, model: str = "") -> bytes:
    """Synthèse ElevenLabs : texte → audio MP3."""
    if not text.strip():
        raise ValueError("Texte vide.")
    payload = {"text": text.strip(), "model_id": model or "eleven_flash_v2_5"}
    response = httpx.post(
        f"{ELEVENLABS_BASE}/v1/text-to-speech/{voice_id}",
        params={"output_format": "mp3_44100_128"},
        json=payload,
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
        timeout=30,
    )
    if response.status_code == 401:
        raise RuntimeError("Clé ElevenLabs refusée (401).")
    if response.status_code == 429:
        raise RuntimeError("ElevenLabs est momentanément saturé (limite de débit).")
    if response.status_code >= 400:
        raise RuntimeError(f"ElevenLabs a refusé la synthèse (HTTP {response.status_code}).")
    return response.content


def probe_chat_tools(
    base: str,
    api_key: str = "",
    model: str = "",
    timeout: float = 20.0,
) -> dict:
    """Test réel : un mini chat avec un outil. Renvoie outil géré ou pas."""
    base = (base or "").strip().rstrip("/")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": "Une charge de 120 euros TTC pour du bois. Appelle l'outil create_entry_draft.",
            }
        ],
        "tools": [PROBE_TOOL],
        "temperature": 0,
        "max_tokens": 200,
    }
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        response = httpx.post(
            f"{base}/chat/completions", headers=headers, json=payload, timeout=timeout
        )
    except httpx.TimeoutException:
        return {"ok": False, "tools": False, "status": 0, "detail": "Le serveur n'a pas répondu à temps."}
    except Exception as exc:
        return {"ok": False, "tools": False, "status": 0, "detail": str(exc)}

    if response.status_code != 200:
        snippet = ""
        try:
            data = response.json()
            if isinstance(data, dict):
                error = data.get("error")
                if isinstance(error, dict):
                    snippet = str(error.get("message") or "")
                elif isinstance(error, str):
                    snippet = error
                if not snippet and data.get("detail"):
                    snippet = str(data["detail"])
                if not snippet and data.get("message"):
                    snippet = str(data["message"])
        except Exception:
            snippet = response.text[:200]
        if response.status_code == 401:
            detail = f"Clé refusée (401) sur {base}/chat/completions"
        elif response.status_code in (403, 407, 511):
            detail = f"Accès refusé ({response.status_code}) sur {base}/chat/completions"
        elif response.status_code == 404:
            detail = f"Chemin introuvable (404) sur {base}/chat/completions"
        elif response.status_code == 400:
            detail = f"Requête refusée (400) sur {base}/chat/completions"
        else:
            detail = f"HTTP {response.status_code} sur {base}/chat/completions"
        if snippet:
            detail += f" — {snippet[:200]}"
        return {"ok": False, "tools": False, "status": response.status_code, "detail": detail}

    try:
        payload = response.json()
    except Exception:
        return {"ok": False, "tools": False, "status": 200, "detail": "Réponse illisible (pas du JSON)."}

    choice = (payload.get("choices") or [{}])[0] if isinstance(payload, dict) else {}
    message = choice.get("message") or {}
    tool_calls = message.get("tool_calls") or []
    if tool_calls:
        return {"ok": True, "tools": True, "status": 200, "detail": "Le modèle répond en appelant les outils."}
    content = (message.get("content") or "").strip()
    if content:
        return {
            "ok": True,
            "tools": False,
            "status": 200,
            "detail": "Le modèle répond, mais sans appeler les outils (tool-calling non géré).",
        }
    return {"ok": False, "tools": False, "status": 200, "detail": "Le serveur renvoie une réponse vide."}


def probe_models_tools(base: str, api_key: str, models: list[str], limit: int = 24, timeout: float = 20.0) -> dict:
    """Probe la compatibilité outil de chaque modèle (concurrence 6, plafonné)."""
    from concurrent.futures import ThreadPoolExecutor

    targets = list(models)[:limit]
    if not targets:
        return {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(probe_chat_tools, base, api_key, m, timeout): m for m in targets}
        results = {}
        for future, model_name in futures.items():
            try:
                outcome = future.result()
                results[model_name] = bool(outcome.get("tools"))
            except Exception:
                results[model_name] = False
    return results


def test_ai_connection(
    base: str, api_key: str = "", model: str = "", timeout: float = 20.0
) -> dict:
    """Test la connexion sur la base /v1 puis la racine, et renvoie la base qui marche."""
    candidates: list[str] = []
    clean = (base or "").strip().rstrip("/")
    if clean.endswith("/v1"):
        candidates = [clean, clean[: -len("/v1")]]
    else:
        candidates = [clean + "/v1", clean]
    last = None
    for candidate in candidates:
        outcome = probe_chat_tools(candidate, api_key, model, timeout=timeout)
        if outcome.get("ok"):
            outcome = {**outcome, "chat_base": candidate}
            return outcome
        last = outcome
    return {**(last or {"ok": False, "tools": False, "status": 0, "detail": "URL absente."}), "chat_base": candidates[0]}
