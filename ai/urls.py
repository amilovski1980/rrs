from django.urls import path

from . import views

urlpatterns = [
    path("session/", views.voice_session, name="voice_session"),
    path("outil/", views.voice_tool, name="voice_tool"),
    path("brouillons/", views.draft_list, name="ai_drafts"),
    path("brouillons/<uuid:pk>/", views.draft_detail, name="ai_draft_detail"),
    path("brouillons/<uuid:pk>/valider/", views.draft_approve, name="ai_draft_approve"),
    path("brouillons/<uuid:pk>/rejeter/", views.draft_reject, name="ai_draft_reject"),
]
