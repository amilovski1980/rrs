from django.contrib import admin
from .models import Company, KbisFile

@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("denomination", "siren", "owner", "regime", "tva", "created_at")
    list_filter = ("regime", "tva", "created_at")
    search_fields = ("denomination", "siren", "email")
    readonly_fields = ("id", "created_at")

@admin.register(KbisFile)
class KbisFileAdmin(admin.ModelAdmin):
    list_display = ("company", "file", "source", "uploaded_at")
    list_filter = ("source", "uploaded_at")
    search_fields = ("company__denomination", "company__siren")
    readonly_fields = ("uploaded_at",)