import uuid

from django.conf import settings
from django.db import models


class Conversation(models.Model):
    """Fil de dialogue avec le modèle AminiAself-hébergé (vLLM, API OpenAI-compatible)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversations"
    )
    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="ai_conversations"
    )
    kind = models.CharField(
        max_length=12,
        choices=[("assist", "assistant"), ("agent", "agent (brouillons)")],
        default="assist",
    )
    created_at = models.DateTimeField(auto_now_add=True)


class Message(models.Model):
    ROLES = [("user", "user"), ("assistant", "assistant"), ("system", "system")]
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=ROLES)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


class AiDraftEntry(models.Model):
    """Brouillon préparé par l'agent IA. Toujours soumis à validation humaine."""

    KIND_CHOICES = [
        ("entry", "Écriture"),
        ("client", "Client"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="drafts",
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="ai_drafts",
        null=True,
        blank=True,
    )
    kind = models.CharField(max_length=12, choices=KIND_CHOICES, default="entry")
    document = models.ForeignKey(
        "documents.Invoice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_drafts",
    )
    created_client = models.ForeignKey(
        "documents.Client",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_drafts",
    )
    ocr_text = models.TextField(blank=True)
    proposed_lines = models.JSONField(
        default=list,
        blank=True,
        help_text='[{"account_code": "601", "debit": "120.00", "credit": "0"}]',
    )
    proposed_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Payload pour les brouillons non-écriture (ex. client).",
    )
    model_name = models.CharField(max_length=40, default="qwen3-32b-awq")
    status = models.CharField(
        max_length=12,
        choices=[("pending", "En attente"), ("validated", "Validé"), ("rejected", "Rejeté")],
        default="pending",
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def resolve_company(self):
        if self.company_id:
            return self.company
        if self.conversation_id:
            return self.conversation.company
        return None
