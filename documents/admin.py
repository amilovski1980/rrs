from django.contrib import admin
from .models import Invoice, InvoiceSeries

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("number", "company", "client_name", "amount_ht", "status", "created_at")
    list_filter = ("status", "created_at", "company")
    search_fields = ("number", "client_name", "client_siren")
    readonly_fields = ("id", "number", "created_at")

@admin.register(InvoiceSeries)
class InvoiceSeriesAdmin(admin.ModelAdmin):
    list_display = ("company", "prefix", "year", "last_number")
    list_filter = ("year", "prefix")
    search_fields = ("company__denomination", "company__siren")