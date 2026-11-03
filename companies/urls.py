from django.urls import path

from . import views

urlpatterns = [
    path("", views.landing, name="landing"),
    path("cockpit/", views.cockpit, name="cockpit"),
    path("ajouter/", views.onboarding, name="onboarding"),
    path("ajouter/confirmer/", views.onboarding_confirm, name="onboarding_confirm"),
    path("societe/", views.company_settings, name="company_settings"),
    path("societe/logo/", views.company_logo, name="company_logo"),
]
