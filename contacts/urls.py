from django.urls import path

from . import views

urlpatterns = [
    path("", views.contact_list, name="contacts"),
    path("nouveau/", views.contact_create, name="contact_create"),
    path("<uuid:pk>/", views.contact_detail, name="contact_detail"),
    path("<uuid:pk>/modifier/", views.contact_edit, name="contact_edit"),
    path("<uuid:pk>/supprimer/", views.contact_delete, name="contact_delete"),
]
