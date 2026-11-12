from django.urls import path

from . import views

urlpatterns = [
    path("forfait/", views.upgrade, name="plan_upgrade"),
    path("forfait/payer/", views.checkout, name="plan_checkout"),
    path("abonnement/stripe/webhook/", views.stripe_webhook, name="stripe_webhook"),
]
