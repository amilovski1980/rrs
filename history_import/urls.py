from django.urls import path

from . import views

app_name = "history_import"

urlpatterns = [
    path("", views.upload, name="upload"),
    path("lots/<uuid:pk>/", views.batch_detail, name="batch"),
    path("lots/<uuid:pk>/analyser/", views.batch_process, name="batch_process"),
    path("lots/<uuid:pk>/importer/", views.batch_import, name="batch_import"),
    path("documents/<uuid:pk>/", views.document_detail, name="document"),
    path("documents/<uuid:pk>/fichier/", views.document_file, name="document_file"),
    path("documents/<uuid:pk>/importer/", views.document_import, name="document_import"),
    path("documents/<uuid:pk>/reanalyser/", views.document_reanalyze, name="document_reanalyze"),
    path("documents/<uuid:pk>/exclure/", views.document_reject, name="document_reject"),
]
