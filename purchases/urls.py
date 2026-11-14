from django.urls import path

from . import views

app_name = "purchases"

urlpatterns = [
    path("", views.purchase_dashboard, name="dashboard"),
    path("factures/", views.invoice_list, name="list"),
    path("factures/nouvelle/", views.invoice_create, name="create"),
    path("factures/importer-pdf/", views.invoice_import_pdf, name="import_pdf"),
    path("factures/<uuid:pk>/", views.invoice_detail, name="detail"),
    path("factures/<uuid:pk>/valider/", views.invoice_approve, name="approve"),
    path("factures/<uuid:pk>/payer/", views.invoice_pay, name="pay"),
    path("factures/<uuid:pk>/ignorer/", views.invoice_ignore, name="ignore"),
    path("factures/<uuid:pk>/justificatif/", views.invoice_attachment, name="attachment"),
    path("paiements/", views.payment_list, name="payments"),
    path("paiements/<uuid:pk>/supprimer/", views.payment_delete, name="payment_delete"),
]
