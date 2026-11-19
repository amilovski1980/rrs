from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from core import demo
from core.pwa import serve_manifest, serve_service_worker
from documents.views import invoice_verify

urlpatterns = [
    # Vérification publique des factures (QR code) : URL courte à la racine.
    path("v/<uuid:pk>/", invoice_verify, name="invoice_verify_root"),
    path("sw.js", serve_service_worker, name="service_worker"),
    path("pwa/manifest.webmanifest", serve_manifest, name="pwa_manifest"),
    path("admin-backoffice/", include("admin_backoffice.urls", namespace="admin_backoffice")),
    path("admin/", admin.site.urls),
    path("", include("companies.urls")),      # cockpit + onboarding
    path("compte/", include("accounts.urls")),  # magic link, logout, profil
    path("compta/", include("accounting.urls")),
    path("factures/", include("documents.urls")),
    path("contacts/", include("contacts.urls")),
    path("mail/", include("mailsync.urls")),
    path("immobilisations/", include("assets.urls")),
    path("comptes-annuels/", include("accounting.annual_reports.urls")),
    path("aminia/", RedirectView.as_view(url="/", permanent=False)),
    path("fournisseurs/", include("suppliers.urls")),
    path("achats/", include("purchases.urls")),
    path("tresorerie/", include("treasury.urls")),
    path("banque/", include("banking.urls")),
    path("migration/", include("history_import.urls")),
    path("agent/", include("ai.urls")),
    path("", include("billing.urls")),
    path("agent-config", demo.agent_config, name="agent_config"),
]
