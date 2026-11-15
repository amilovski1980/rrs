from django.urls import path

from . import views

app_name = "suppliers"

urlpatterns = [
    path("", views.supplier_list, name="list"),
    path("nouveau/", views.supplier_create, name="create"),
    path("rechercher/", views.supplier_lookup, name="lookup"),
    path("<uuid:pk>/", views.supplier_detail, name="detail"),
    path("<uuid:pk>/modifier/", views.supplier_edit, name="edit"),
    path("<uuid:pk>/activer/", views.supplier_toggle, name="toggle"),
]
