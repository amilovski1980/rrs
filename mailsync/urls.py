from django.urls import path

from . import views

app_name = "mailsync"

urlpatterns = [
    path("parametres/", views.connector_settings, name="settings"),
    path("connecter/<str:provider_id>/", views.connect, name="connect"),
    path("callback/<str:provider_id>/", views.oauth_callback, name="oauth_callback"),
    path("deconnecter/", views.disconnect, name="disconnect"),
    path("verifier-maintenant/", views.sync_now, name="sync_now"),
    path("brouillons/", views.draft_list, name="drafts"),
    path("brouillons/<uuid:pk>/", views.draft_detail, name="draft_detail"),
    path("brouillons/<uuid:pk>/pdf/", views.draft_pdf, name="draft_pdf"),
    path("brouillons/<uuid:pk>/valider/", views.draft_validate, name="draft_validate"),
    path("brouillons/<uuid:pk>/ignorer/", views.draft_ignore, name="draft_ignore"),
]
