from django.urls import path

from . import views

urlpatterns = [
    path("ecriture/nouvelle/", views.entry_create, name="entry_create"),
    path("grand-livre/", views.ledger, name="ledger"),
    path("balance/", views.balance, name="balance"),
]
