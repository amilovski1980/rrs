from django.urls import path

from . import views

app_name = "banking"

urlpatterns = [
    path("", views.bank_dashboard, name="dashboard"),
    path("comptes/", views.account_list, name="accounts"),
    path("comptes/nouveau/", views.account_create, name="account_create"),
    path("comptes/<uuid:pk>/", views.account_detail, name="account_detail"),
    path("comptes/<uuid:pk>/modifier/", views.account_edit, name="account_edit"),
    path("import/", views.statement_import, name="import"),
    path("transactions/", views.transaction_list, name="transactions"),
    path("transactions/<uuid:pk>/", views.transaction_detail, name="transaction_detail"),
    path("transactions/<uuid:pk>/rapprocher/", views.transaction_match, name="transaction_match"),
    path("transactions/<uuid:pk>/creer-ecriture/", views.transaction_create_entry, name="transaction_entry"),
    path("transactions/<uuid:pk>/de-rapprocher/", views.transaction_unmatch, name="transaction_unmatch"),
    path("transactions/<uuid:pk>/ignorer/", views.transaction_ignore, name="transaction_ignore"),
    path("regles/", views.rule_list, name="rules"),
    path("regles/nouvelle/", views.rule_create, name="rule_create"),
    path("regles/<uuid:pk>/modifier/", views.rule_edit, name="rule_edit"),
    path("regles/<uuid:pk>/activer/", views.rule_toggle, name="rule_toggle"),
    path("releves/<uuid:pk>/fichier/", views.statement_file, name="statement_file"),
]
