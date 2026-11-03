from django.urls import path

from . import views

urlpatterns = [
    path("", views.invoice_list, name="invoices"),
    path("nouvelle/", views.invoice_create, name="invoice_create"),
    path("<uuid:pk>/modifier/", views.invoice_edit, name="invoice_edit"),
    path("<uuid:pk>/pdf/", views.invoice_pdf, name="invoice_pdf"),
    path("<uuid:pk>/", views.invoice_detail, name="invoice_detail"),
    path("<uuid:pk>/emettre/", views.invoice_issue, name="invoice_issue"),
    path("<uuid:pk>/payer/", views.invoice_pay, name="invoice_pay"),
]
