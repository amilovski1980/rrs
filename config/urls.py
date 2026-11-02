from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from core import demo

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("companies.urls")),      # cockpit + onboarding
    path("compte/", include("accounts.urls")),  # magic link, logout, profil
    path("compta/", include("accounting.urls")),
    path("agent-config", demo.agent_config, name="agent_config"),
    # path("factures/", include("documents.urls")),
    # path("ia/", include("ai.urls")),
    # path("webhooks/", include("integrations.urls")),
]
