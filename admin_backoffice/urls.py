from django.urls import path
from . import views
from django.http import HttpResponse

app_name = "admin_backoffice"

def health_check(request):
    return HttpResponse("Admin Backoffice is ALIVE")


def _diag_tables(request):
    """Diagnostic temporaire : état de chaque table + rendu du template dashboard."""
    from pathlib import Path

    from django.conf import settings
    from django.contrib.auth.models import User as DjangoUser
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    from django.template.loader import render_to_string

    from accounts.models import User
    from ai.models import AiDraftEntry
    from billing.models import Plan, Subscription
    from companies.models import Company

    from .models import SiteConfiguration, SystemLog

    lines = ["DIAG v3"]
    migdir = Path(settings.BASE_DIR) / "admin_backoffice" / "migrations"
    if migdir.is_dir():
        lines.append(f"migrations embarquées: {sorted(p.name for p in migdir.iterdir())}")
    else:
        lines.append("migrations embarquées: ABSENT du bundle")
    try:
        src = (Path(settings.BASE_DIR) / "api" / "index.py").read_text(encoding="utf-8", errors="replace")
        extrait = " | ".join(
            l.strip() for l in src.splitlines()
            if "call_command" in l or "migrate" in l or "DATABASE_URL" in l
        )[:300]
        lines.append(f"api/index.py embarqué (extraits): {extrait}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"api/index.py: non lisible ({type(exc).__name__}: {exc})")
    db = settings.DATABASES["default"]
    lines.append(
        f"DB: engine={db['ENGINE']} name={db.get('NAME')} host={db.get('HOST') or '(local)'}"
    )
    try:
        from django.core.management import call_command
        from io import StringIO

        tampon = StringIO()
        call_command("migrate", verbosity=1, interactive=False, stdout=tampon)
        lignes_mig = [l for l in tampon.getvalue().splitlines() if l.strip()][-8:]
        lines.append("migrate à la demande: OK (" + " ; ".join(l.strip() for l in lignes_mig) + ")")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"migrate à la demande: ERREUR {type(exc).__name__}: {exc}")
    try:
        executor = MigrationExecutor(connection)
        appliquees = sorted(
            name for app, name in executor.loader.applied_migrations if app == "admin_backoffice"
        )
        lines.append(f"migrations admin_backoffice appliquées: {appliquees}")
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        en_attente = sorted(
            f"{m.app_label}.{m.name}" for m, _ in plan if m.app_label == "admin_backoffice"
        )
        lines.append(f"admin_backoffice en attente: {en_attente}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"MigrationExecutor: ERREUR {type(exc).__name__}: {exc}")

    probes = [
        ("accounts.User", lambda: User.objects.count()),
        ("companies.Company", lambda: Company.objects.count()),
        ("billing.Plan", lambda: Plan.objects.count()),
        ("billing.Subscription", lambda: Subscription.objects.count()),
        ("ai.AiDraftEntry", lambda: AiDraftEntry.objects.count()),
        ("admin_backoffice.SiteConfiguration", lambda: SiteConfiguration.objects.count()),
        ("admin_backoffice.SystemLog", lambda: SystemLog.objects.count()),
    ]
    for label, fn in probes:
        try:
            lines.append(f"{label}: OK ({fn()})")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"{label}: ERREUR {type(exc).__name__}: {exc}")

    try:
        html = render_to_string(
            "admin_backoffice/dashboard.html",
            {
                "total_users": "?",
                "total_companies": "?",
                "mrr": "0",
                "subs_past_due": "?",
                "ai_validation_rate": "0%",
                "total_ai_drafts": "?",
                "recent_companies": Company.objects.order_by("-created_at")[:5],
                "recent_logs": SystemLog.objects.all().order_by("-timestamp")[:10],
            },
        )
        lines.append(f"rendu dashboard: OK ({len(html)} octets)")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"rendu dashboard: ERREUR {type(exc).__name__}: {exc}")

    return HttpResponse(" || ".join(lines), content_type="text/plain")


urlpatterns = [
    # Health Check
    path('health/', health_check, name='health'),
    # Diagnostic temporaire (à retirer après vérification)
    path('diag/', _diag_tables),
    # Dashboard & Config
    path('', views.DashboardView.as_view(), name='dashboard'),
    path('dashboard/', views.DashboardView.as_view(), name='dashboard_url'),
    path('settings/', views.SiteSettingsView.as_view(), name='settings'),
    path('logs/', views.SystemLogsView.as_view(), name='logs'),

    # CRUD Companies
    path('companies/', views.CompanyListView.as_view(), name='companies'),
    path('companies/list/', views.CompanyListView.as_view(), name='companies_list'),
    path('companies/create/', views.CompanyCreateView.as_view(), name='company_create'),
    path('companies/<uuid:pk>/edit/', views.CompanyUpdateView.as_view(), name='company_edit'),
    path('companies/<uuid:pk>/delete/', views.CompanyDeleteView.as_view(), name='company_delete'),

    # CRUD Plans
    path('plans/', views.PlanListView.as_view(), name='plans'),
    path('plans/list/', views.PlanListView.as_view(), name='plans_list'),
    path('plans/create/', views.PlanCreateView.as_view(), name='plan_create'),
    path('plans/<int:pk>/edit/', views.PlanUpdateView.as_view(), name='plan_edit'),
    path('plans/<int:pk>/delete/', views.PlanDeleteView.as_view(), name='plan_delete'),

    # CRUD Subscriptions
    path('subscriptions/', views.SubscriptionListView.as_view(), name='subscriptions'),
    path('subscriptions/list/', views.SubscriptionListView.as_view(), name='subscriptions_list'),
    path('subscriptions/create/', views.SubscriptionCreateView.as_view(), name='subscription_create'),
    path('subscriptions/<int:pk>/edit/', views.SubscriptionUpdateView.as_view(), name='subscription_edit'),
    path('subscriptions/<int:pk>/delete/', views.SubscriptionDeleteView.as_view(), name='subscription_delete'),

    # CRUD Users
    path('users/', views.UserListView.as_view(), name='users'),
    path('users/<uuid:pk>/edit/', views.UserUpdateView.as_view(), name='user_edit'),
    path('users/<uuid:pk>/delete/', views.UserDeleteView.as_view(), name='user_delete'),

    # AI Monitoring
    path('ai-monitoring/', views.AiMonitoringView.as_view(), name='ai_monitoring'),
    path('ai-prompt/', views.AiPromptView.as_view(), name='ai_prompt'),
]
