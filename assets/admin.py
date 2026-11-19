from django.contrib import admin
from .models import Asset, DepreciationSchedule


class DepreciationScheduleInline(admin.TabularInline):
    model = DepreciationSchedule
    extra = 0


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "acquisition_date", "cost")
    search_fields = ("name", "company__denomination")
    inlines = [DepreciationScheduleInline]
