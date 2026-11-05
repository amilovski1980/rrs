from django.urls import path

from . import views

urlpatterns = [
    path("", views.invoice_list, name="invoices"),
    path("nouvelle/", views.invoice_create, name="invoice_create"),
    path("import-pdf/", views.invoice_import_pdf, name="invoice_import_pdf"),
    path("<uuid:pk>/modifier/", views.invoice_edit, name="invoice_edit"),
    path("<uuid:pk>/pdf/", views.invoice_pdf, name="invoice_pdf"),
    path("<uuid:pk>/", views.invoice_detail, name="invoice_detail"),
    path("<uuid:pk>/emettre/", views.invoice_issue, name="invoice_issue"),
    path("<uuid:pk>/payer/", views.invoice_pay, name="invoice_pay"),
    path("<uuid:pk>/supprimer/", views.invoice_delete, name="invoice_delete"),

    path("clients/", views.client_list, name="clients"),
    path("clients/nouveau/", views.client_create, name="client_create"),
    path("clients/<uuid:pk>/", views.client_detail, name="client_detail"),
    path("clients/<uuid:pk>/modifier/", views.client_edit, name="client_edit"),
    path("clients/<uuid:pk>/supprimer/", views.client_delete, name="client_delete"),

    path("produits/", views.product_list, name="products"),
    path("produits/nouveau/", views.product_create, name="product_create"),
    path("produits/<uuid:pk>/", views.product_detail, name="product_detail"),
    path("produits/<uuid:pk>/modifier/", views.product_edit, name="product_edit"),
    path("produits/<uuid:pk>/supprimer/", views.product_delete, name="product_delete"),

    path("projets/", views.project_list, name="projects"),
    path("projets/nouveau/", views.project_create, name="project_create"),
    path("projets/<uuid:pk>/", views.project_detail, name="project_detail"),
    path("projets/<uuid:pk>/modifier/", views.project_edit, name="project_edit"),
    path("projets/<uuid:pk>/supprimer/", views.project_delete, name="project_delete"),

    path("devis/", views.quote_list, name="quotes"),
    path("devis/nouveau/", views.quote_create, name="quote_create"),
    path("devis/<uuid:pk>/", views.quote_detail, name="quote_detail"),
    path("devis/<uuid:pk>/modifier/", views.quote_edit, name="quote_edit"),
    path("devis/<uuid:pk>/numeroter/", views.quote_issue, name="quote_issue"),
    path("devis/<uuid:pk>/convertir/", views.quote_convert, name="quote_convert"),
    path("devis/<uuid:pk>/supprimer/", views.quote_delete, name="quote_delete"),

    path("avoirs/", views.credit_note_list, name="credit_notes"),
    path("avoirs/nouveau/", views.credit_note_create, name="credit_note_create"),
    path("avoirs/<uuid:pk>/", views.credit_note_detail, name="credit_note_detail"),
    path("avoirs/<uuid:pk>/modifier/", views.credit_note_edit, name="credit_note_edit"),
    path("avoirs/<uuid:pk>/emettre/", views.credit_note_issue, name="credit_note_issue"),
    path("avoirs/<uuid:pk>/supprimer/", views.credit_note_delete, name="credit_note_delete"),

    path("paiements/", views.payment_list, name="payments"),
    path("paiements/nouveau/", views.payment_create, name="payment_create"),
    path("paiements/<uuid:pk>/", views.payment_detail, name="payment_detail"),
    path("paiements/<uuid:pk>/supprimer/", views.payment_delete, name="payment_delete"),
]
