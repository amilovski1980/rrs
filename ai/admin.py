from django.contrib import admin
from .models import Conversation, Message, AiDraftEntry

@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "company", "kind", "created_at")
    list_filter = ("kind", "created_at")
    search_fields = ("user__email", "company__denomination")

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "role", "created_at")
    list_filter = ("role", "created_at")
    search_fields = ("content",)

@admin.register(AiDraftEntry)
class AiDraftEntryAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "company", "conversation", "document", "status", "model_name", "created_at")
    list_filter = ("kind", "status", "model_name", "created_at")
    search_fields = ("ocr_text",)
    readonly_fields = ("id", "created_at", "validated_at")
