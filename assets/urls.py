from django.urls import path

from . import views

app_name = "assets"

urlpatterns = [
    path("", views.asset_list, name="list"),
    path("nouveau/", views.asset_create, name="create"),
    path("<uuid:pk>/modifier/", views.asset_update, name="update"),
    path("<uuid:pk>/supprimer/", views.asset_delete, name="delete"),
]
