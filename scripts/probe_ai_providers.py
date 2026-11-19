# Diagnostic des fournisseurs IA disponibles localement.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from ai.providers import text_provider

p = text_provider()
print(
    "code:", p["code"],
    "| base:", p["base"],
    "| model:", p["model"],
    "| key:", "oui" if p["key"] else "non",
    "| configured:", p["configured"],
)
print("--- variables d'environnement ---")
for key in ("XAI_API_KEY", "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "OLLAMA_BASE_URL", "QWEN_API_KEY", "DASHSCOPE_API_KEY"):
    value = os.environ.get(key)
    print(key, ":", (str(value)[:30] + "…" if value else "ABSENT"))
from admin_backoffice.models import AgentSettings

config = AgentSettings.objects.first()
if config:
    print(
        "--- base IA (SQL) ---",
        "provider:", config.ai_text_provider,
        "| llm_base_url:", (config.llm_base_url or "")[:40],
        "| model:", config.llm_model or "",
        "| key:", "oui" if config.llm_api_key else "non",
    )
