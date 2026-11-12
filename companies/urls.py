from django.urls import path

from . import signup, views

urlpatterns = [
    path("", views.landing, name="landing"),
    path("recherche/", signup.company_search, name="company_search"),
    path("inscription/", signup.signup_wizard, name="signup_wizard"),
    path("inscription/choisir/", signup.signup_start, name="signup_start"),
    path("inscription/verifier/", signup.signup_pending, name="signup_pending"),
    path("inscription/verifier/<str:token>/", signup.signup_verify, name="signup_verify"),
    path("inscription/telephone/", signup.signup_phone_check, name="signup_phone_check"),
    path("cockpit/", views.cockpit, name="cockpit"),
    path("ajouter/", views.onboarding, name="onboarding"),
    path("ajouter/confirmer/", views.onboarding_confirm, name="onboarding_confirm"),
    path("societe/", views.company_settings, name="company_settings"),
    path("societe/logo/", views.company_logo, name="company_logo"),
    path("aide/", views.help_page, name="help"),
    path("mentions-legales/", views.legal_notice, name="legal_notice"),
]
