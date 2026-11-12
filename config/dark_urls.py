"""Parcours public sous /dark. Le cockpit et le back-office restent aux URLs d'origine."""
from django.urls import path

from accounts import views as account_views
from companies import signup
from companies import views

app_name = "dark"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("recherche/", signup.company_search, name="company_search"),
    path("inscription/", signup.signup_wizard, name="signup_wizard"),
    path("inscription/choisir/", signup.signup_start, name="signup_start"),
    path("inscription/verifier/", signup.signup_pending, name="signup_pending"),
    path("inscription/verifier/<str:token>/", signup.signup_verify, name="signup_verify"),
    path("inscription/telephone/", signup.signup_phone_check, name="signup_phone_check"),
    path("compte/", account_views.login_view, name="magic_link_request"),
    path("compte/lien/", account_views.magic_link_email, name="magic_link_email"),
    path("compte/lien/envoye/", account_views.magic_link_email_done, name="magic_link_email_done"),
    path("compte/magic/<str:token>/", account_views.magic_link_verify, name="magic_link_verify"),
    path("compte/mot-de-passe/oublie/", account_views.FrenchPasswordResetView.as_view(), name="password_reset"),
    path("compte/mot-de-passe/envoye/", account_views.FrenchPasswordResetDoneView.as_view(), name="password_reset_done"),
    path(
        "compte/mot-de-passe/<uidb64>/<token>/",
        account_views.FrenchPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "compte/mot-de-passe/modifie/",
        account_views.FrenchPasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
]
