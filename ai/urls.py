from django.urls import path

from . import views

urlpatterns = [
    path("session/", views.voice_session, name="voice_session"),
    path("outil/", views.voice_tool, name="voice_tool"),
]
