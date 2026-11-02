from django.urls import path

from . import views

urlpatterns = [
    path("", views.magic_link_request, name="magic_link_request"),
    path("magic/<str:token>/", views.magic_link_verify, name="magic_link_verify"),
    path("logout/", views.logout_view, name="logout"),
    path("profil/", views.profile, name="profile"),
]
