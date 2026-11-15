from django.contrib import admin

from .models import ImportAuditEvent, ImportBatch, ImportDocument


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = ("label", "company", "status", "kind_hint", "created_at")
    list_filter = ("status", "kind_hint")
    search_fields = ("label", "company__denomination")


@admin.register(ImportDocument)
class ImportDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "original_name",
        "company",
        "kind",
        "status",
        "invoice_number",
        "amount_ttc",
        "created_at",
    )
    list_filter = ("status", "kind")
    search_fields = ("original_name", "invoice_number", "seller_name", "customer_name")
    readonly_fields = ("checksum", "extracted", "warnings", "raw_text", "created_at")


@admin.register(ImportAuditEvent)
class ImportAuditEventAdmin(admin.ModelAdmin):
    list_display = ("action", "company", "batch", "document", "user", "created_at")
    list_filter = ("action",)
    readonly_fields = ("created_at",)
