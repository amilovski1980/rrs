from django.urls import path

from . import views

urlpatterns = [
    path("ecriture/nouvelle/", views.entry_create, name="entry_create"),
    path("grand-livre/", views.ledger, name="ledger"),
    path("ecriture/<uuid:pk>/valider/", views.entry_validate, name="entry_validate"),
    path("balance/", views.balance, name="balance"),
    path("export-fec/", views.export_fec, name="export_fec"),
]
