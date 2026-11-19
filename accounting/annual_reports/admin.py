from django.contrib import admin
from .models import AnnualAccount


@admin.register(AnnualAccount)
class AnnualAccountAdmin(admin.ModelAdmin):
    list_display = ('company', 'year', 'total_assets', 'total_liabilities', 'total_equity')
    list_filter = ('year',)
    search_fields = ('company__denomination',)
