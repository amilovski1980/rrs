from django.contrib import admin

from .models import (
    Client,
    CreditNote,
    Invoice,
    InvoiceLine,
    InvoiceSeries,
    Payment,
    Product,
    Project,
    Quote,
    QuoteLine,
)


class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 0


class QuoteLineInline(admin.TabularInline):
    model = QuoteLine
    extra = 0


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "siren", "email", "created_at")
    list_filter = ("company", "created_at")
    search_fields = ("name", "siren", "email")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("label", "company", "unit_price", "vat_rate", "active")
    list_filter = ("active", "company")
    search_fields = ("label",)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "client", "status", "created_at")
    list_filter = ("status", "company")
    search_fields = ("name",)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("number", "company", "client_name", "amount_ht", "status", "created_at")
    list_filter = ("status", "created_at", "company")
    search_fields = ("number", "client_name", "client_siren")
    readonly_fields = ("id", "number", "created_at")
    inlines = [InvoiceLineInline]


@admin.register(InvoiceSeries)
class InvoiceSeriesAdmin(admin.ModelAdmin):
    list_display = ("company", "prefix", "year", "last_number")
    list_filter = ("year", "prefix")
    search_fields = ("company__denomination", "company__siren")


@admin.register(Quote)
class QuoteAdmin(admin.ModelAdmin):
    list_display = ("number", "company", "client_name", "amount_ht", "status", "created_at")
    list_filter = ("status", "company")
    search_fields = ("number", "client_name")
    inlines = [QuoteLineInline]


@admin.register(CreditNote)
class CreditNoteAdmin(admin.ModelAdmin):
    list_display = ("number", "company", "invoice", "amount_ht", "status", "created_at")
    list_filter = ("status", "company")
    search_fields = ("number", "invoice__number")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("invoice", "company", "amount", "method", "paid_at")
    list_filter = ("method", "paid_at", "company")
    search_fields = ("invoice__number", "reference")
