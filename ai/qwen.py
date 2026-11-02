import json

import httpx
from django.conf import settings


class QwenClient:
    """Client du LLM self-hosté AminiAvLLM (API OpenAI-compatible).

    - Assistant : chat uni-turn sur RAG des guides compta.
    - Agent     : tool-callings sur API interne (create_entry_draft, suggest_account).
    """

    def __init__(self):
        self.base = settings.LLM_BASE_URL.rstrip("/")
        self.model = settings.LLM_MODEL
        self.api_key = settings.LLM_API_KEY

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        payload = {"model": self.model, "messages": messages, "temperature": 0.2}
        if tools:
            payload["tools"] = tools
        r = httpx.post(
            f"{self.base}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
            json=payload,
            timeout=120,
        )
        r.raise_for_status()
        return r.json()

    # def embed(...)  # avec Qwen3-Embedding ou BGE-M3 (self-host), pour le RAG.
    # TODO (S3): intégrer le RAG pgvector sur les guides micro/reel + fiches par activité.
