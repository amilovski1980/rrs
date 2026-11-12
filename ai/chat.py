"""Chat texte Aminia : Conversation/Message + QwenClient + outils assistant."""
from __future__ import annotations

import json
from typing import Any

from django.conf import settings

from .assistant import TOOLS, execute_tool
from .models import Conversation, Message
from .qwen import QwenClient

UNAVAILABLE = (
    "Aminia (chat) n'est pas disponible pour le moment : "
    "l'assistant texte n'est pas configuré ou joignable. "
    "Réessayez plus tard, ou utilisez le mode vocal."
)


def llm_configured() -> bool:
    base = (getattr(settings, "LLM_BASE_URL", "") or "").strip()
    return bool(base)


def _openai_tools():
    """Convertit les outils xAI realtime vers le format OpenAI chat.completions."""
    out = []
    for tool in TOOLS:
        out.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters") or {"type": "object", "properties": {}},
                },
            }
        )
    return out


def _text_instructions(user, company) -> str:
    from .prompts import agent_instructions

    return agent_instructions(user, company, channel="chat")


def get_or_create_conversation(user, company) -> Conversation:
    conv = (
        Conversation.objects.filter(user=user, company=company, kind="assist")
        .order_by("-created_at")
        .first()
    )
    if conv is None:
        conv = Conversation.objects.create(user=user, company=company, kind="assist")
    return conv


def _history(conversation: Conversation, limit: int = 24) -> list[dict]:
    qs = conversation.messages.order_by("created_at")
    total = qs.count()
    start = max(0, total - limit)
    return [{"role": m.role, "content": m.content} for m in qs[start:]]


def run_chat_turn(user, company, conversation: Conversation, text: str, client: QwenClient | None = None) -> dict[str, Any]:
    """Enregistre le message user, appelle le LLM (outils), renvoie la réponse assistant."""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "Message vide.", "status": 400}
    if len(text) > 2000:
        return {"ok": False, "error": "Message trop long (2 000 caractères max).", "status": 400}

    Message.objects.create(conversation=conversation, role="user", content=text)

    if not llm_configured():
        reply = UNAVAILABLE
        msg = Message.objects.create(conversation=conversation, role="assistant", content=reply)
        return {
            "ok": True,
            "fallback": True,
            "reply": reply,
            "conversation_id": str(conversation.id),
            "message_id": str(msg.id),
        }

    messages: list[dict] = [{"role": "system", "content": _text_instructions(user, company)}]
    messages.extend(_history(conversation))

    client = client or QwenClient()
    from admin_backoffice.agent_prompts import tool_allowed

    tools = [
        tool for tool in _openai_tools()
        if tool_allowed(user, tool["function"]["name"])
    ] or None
    session_company = company

    def remember(selected):
        nonlocal session_company
        session_company = selected

    try:
        reply_text = ""
        for _ in range(4):
            raw = client.chat(messages, tools=tools)
            choice = (raw.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            tool_calls = message.get("tool_calls") or []
            content = (message.get("content") or "").strip()
            if tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": content or None,
                        "tool_calls": tool_calls,
                    }
                )
                for call in tool_calls:
                    fn = call.get("function") or {}
                    name = fn.get("name") or ""
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    result = execute_tool(user, session_company, name, args, remember)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id") or name,
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
                continue
            reply_text = content or "D’accord."
            break
        if not reply_text:
            reply_text = "D’accord."
    except Exception:
        reply_text = UNAVAILABLE
        msg = Message.objects.create(conversation=conversation, role="assistant", content=reply_text)
        return {
            "ok": True,
            "fallback": True,
            "reply": reply_text,
            "conversation_id": str(conversation.id),
            "message_id": str(msg.id),
        }

    msg = Message.objects.create(conversation=conversation, role="assistant", content=reply_text)
    return {
        "ok": True,
        "fallback": False,
        "reply": reply_text,
        "conversation_id": str(conversation.id),
        "message_id": str(msg.id),
    }
