from django.urls import path

from . import views
from core.demo import demo_login

urlpatterns = [
    path("demo/", demo_login, name="demo_login"),
    path("", views.login_view, name="magic_link_request"),
    path("lien/", views.magic_link_email, name="magic_link_email"),
    path("lien/envoye/", views.magic_link_email_done, name="magic_link_email_done"),
    path("magic/<str:token>/", views.magic_link_verify, name="magic_link_verify"),
    path("mot-de-passe/oublie/", views.FrenchPasswordResetView.as_view(), name="password_reset"),
    path("mot-de-passe/envoye/", views.FrenchPasswordResetDoneView.as_view(), name="password_reset_done"),
    path(
        "mot-de-passe/<uidb64>/<token>/",
        views.FrenchPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path("mot-de-passe/modifie/", views.FrenchPasswordResetCompleteView.as_view(), name="password_reset_complete"),
    path("logout/", views.logout_view, name="logout"),
    path("profil/", views.profile, name="profile"),
]
