from django.contrib import admin

from .models import MailboxConfig, ProcessedEmail, Supplier, SupplierInvoiceDraft


@admin.register(MailboxConfig)
class MailboxConfigAdmin(admin.ModelAdmin):
    list_display = (
        "company",
        "provider",
        "email_address",
        "frequency_minutes",
        "is_active",
        "status",
        "last_sync_at",
    )
    list_filter = ("provider", "is_active", "status")
    search_fields = ("company__denomination", "email_address")
    readonly_fields = (
        "access_token_enc",
        "refresh_token_enc",
        "token_expires_at",
        "granted_scopes",
        "last_sync_at",
        "last_error",
        "created_at",
        "updated_at",
    )


@admin.register(ProcessedEmail)
class ProcessedEmailAdmin(admin.ModelAdmin):
    list_display = ("subject", "from_email", "status", "received_at", "created_at")
    list_filter = ("status",)
    search_fields = ("subject", "from_email", "message_id")
    readonly_fields = ("created_at",)


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "company",
        "siret",
        "tva_intra",
        "email",
        "payment_terms_days",
        "is_active",
        "created_from",
    )
    list_filter = ("is_active", "created_from")
    search_fields = ("name", "siret", "tva_intra", "email")


@admin.register(SupplierInvoiceDraft)
class SupplierInvoiceDraftAdmin(admin.ModelAdmin):
    list_display = (
        "proposed_supplier_name",
        "invoice_number",
        "invoice_date",
        "amount_ttc",
        "source",
        "status",
        "company",
    )
    list_filter = ("status", "source")
    search_fields = ("proposed_supplier_name", "invoice_number", "supplier_siret")
    readonly_fields = ("raw_text", "created_at", "validated_at")
