from django.contrib import admin

from .models import PurchaseInvoice, SupplierPayment


class SupplierPaymentInline(admin.TabularInline):
    model = SupplierPayment
    extra = 0
    readonly_fields = ("journal_entry", "created_at")


@admin.register(PurchaseInvoice)
class PurchaseInvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "supplier_name",
        "number",
        "invoice_date",
        "due_date",
        "amount_ttc",
        "status",
        "source",
        "company",
    )
    list_filter = ("status", "source")
    search_fields = ("supplier_name", "number")
    readonly_fields = ("journal_entry", "created_at", "updated_at")
    inlines = [SupplierPaymentInline]


@admin.register(SupplierPayment)
class SupplierPaymentAdmin(admin.ModelAdmin):
    list_display = ("invoice", "amount", "paid_at", "method", "company")
    list_filter = ("method",)
    readonly_fields = ("journal_entry", "created_at")
