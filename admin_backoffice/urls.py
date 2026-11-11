from django.urls import path
from . import views

urlpatterns = [
    path('', views.DashboardView.as_view(), name='dashboard'),
    path('companies/', views.CompanyListView.as_view(), name='companies_list'),
    path('subscriptions/', views.SubscriptionListView.as_view(), name='subscriptions_list'),
    path('plans/', views.PlanListView.as_view(), name='plans_list'),
    path('ai-monitoring/', views.AiMonitoringView.as_view(), name='ai_monitoring'),
    path('ai-prompt/', views.AiPromptView.as_view(), name='ai_prompt'),
]