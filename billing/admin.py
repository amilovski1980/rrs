from django.contrib import admin
from .models import Plan, Subscription, StripeEvent

@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "price_eur", "trial_days")
    list_filter = ("price_eur",)
    search_fields = ("code", "name")

@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "status", "current_period_end", "created_at")
    list_filter = ("status", "plan", "created_at")
    search_fields = ("user__email", "stripe_subscription_id")
    readonly_fields = ("id", "created_at", "current_period_end")

@admin.register(StripeEvent)
class StripeEventAdmin(admin.ModelAdmin):
    list_display = ("external_id", "type", "received_at")
    list_filter = ("type", "received_at")
    search_fields = ("external_id", "type")
    readonly_fields = ("received_at",)