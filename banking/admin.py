from django.contrib import admin

from .models import BankAccount, BankRule, BankStatement, BankTransaction


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ("label", "company", "bank_name", "iban", "opening_balance", "is_active")
    list_filter = ("is_active",)
    search_fields = ("label", "bank_name", "iban")


@admin.register(BankStatement)
class BankStatementAdmin(admin.ModelAdmin):
    list_display = ("account", "date_start", "date_end", "source_format", "row_count", "imported_at")
    list_filter = ("source_format",)


@admin.register(BankTransaction)
class BankTransactionAdmin(admin.ModelAdmin):
    list_display = ("date", "label", "amount", "status", "nature", "match_type", "account")
    list_filter = ("status", "nature", "match_type", "account")
    search_fields = ("label", "counterparty", "reference")
    readonly_fields = ("fingerprint", "created_at")


@admin.register(BankRule)
class BankRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "label_contains", "counterpart_account", "is_active", "priority")
    list_filter = ("is_active",)
