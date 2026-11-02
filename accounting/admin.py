from django.contrib import admin

from .models import ChartAccount, EntryLine, Journal, JournalEntry


class EntryLineInline(admin.TabularInline):
    model = EntryLine
    extra = 2


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ("date", "journal", "label", "validated", "drafted_by_ai")
    list_filter = ("journal", "validated")
    search_fields = ("label",)
    inlines = [EntryLineInline]
    list_select_related = ("journal",)


@admin.register(ChartAccount)
class ChartAccountAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "company")
    search_fields = ("code", "label")


admin.site.register(Journal)
