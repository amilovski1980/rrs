from django.contrib import admin

from .models import Supplier


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
    )
    list_filter = ("is_active", "created_from")
    search_fields = ("name", "siret", "tva_intra", "email")
