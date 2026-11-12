from django.urls import path
from . import views
from django.http import HttpResponse

app_name = "admin_backoffice"

def health_check(request):
    return HttpResponse("Admin Backoffice is ALIVE")

urlpatterns = [
    # Health Check
    path('health/', health_check, name='health'),
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
    path('users/<int:pk>/edit/', views.UserUpdateView.as_view(), name='user_edit'),
    path('users/<int:pk>/delete/', views.UserDeleteView.as_view(), name='user_delete'),

    # AI Monitoring
    path('ai-monitoring/', views.AiMonitoringView.as_view(), name='ai_monitoring'),
    path('ai-prompt/', views.AiPromptView.as_view(), name='ai_prompt'),
]
