from django.urls import path

from . import views

app_name = "treasury"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("export/", views.export_forecast, name="export"),
]
