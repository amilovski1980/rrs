from django.urls import path

from . import billing_admin, views

app_name = "admin_backoffice"

urlpatterns = [
    path("health/", views.health_check, name="health"),
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("dashboard/", views.DashboardView.as_view(), name="dashboard_url"),
    path("settings/", views.SiteSettingsView.as_view(), name="settings"),
    path("logs/", views.SystemLogsView.as_view(), name="logs"),

    path("companies/", views.CompanyListView.as_view(), name="companies"),
    path("companies/list/", views.CompanyListView.as_view(), name="companies_list"),
    path("companies/create/", views.CompanyCreateView.as_view(), name="company_create"),
    path("companies/<uuid:pk>/edit/", views.CompanyUpdateView.as_view(), name="company_edit"),
    path("companies/<uuid:pk>/delete/", views.CompanyDeleteView.as_view(), name="company_delete"),

    path("plans/", views.PlanListView.as_view(), name="plans"),
    path("plans/list/", views.PlanListView.as_view(), name="plans_list"),
    path("plans/create/", views.PlanCreateView.as_view(), name="plan_create"),
    path("plans/<int:pk>/edit/", views.PlanUpdateView.as_view(), name="plan_edit"),
    path("plans/<int:pk>/delete/", views.PlanDeleteView.as_view(), name="plan_delete"),

    path("subscriptions/", views.SubscriptionListView.as_view(), name="subscriptions"),
    path("subscriptions/list/", views.SubscriptionListView.as_view(), name="subscriptions_list"),
    path("subscriptions/create/", views.SubscriptionCreateView.as_view(), name="subscription_create"),
    path("subscriptions/<uuid:pk>/edit/", views.SubscriptionUpdateView.as_view(), name="subscription_edit"),
    path("subscriptions/<uuid:pk>/delete/", views.SubscriptionDeleteView.as_view(), name="subscription_delete"),

    path("facturation/", billing_admin.SubscriberListView.as_view(), name="billing"),
    path("facturation/abonnes/<uuid:pk>/", billing_admin.SubscriberDetailView.as_view(), name="billing_subscriber"),
    path("facturation/factures/", billing_admin.BillingInvoiceListView.as_view(), name="billing_invoices"),
    path("facturation/factures/<uuid:pk>/", billing_admin.BillingInvoiceDetailView.as_view(), name="billing_invoice"),
    path("users/<uuid:pk>/facturation/", billing_admin.UserBillingView.as_view(), name="user_billing"),
    path("companies/<uuid:pk>/facturation/", billing_admin.CompanyBillingView.as_view(), name="company_billing"),

    path("users/", views.UserListView.as_view(), name="users"),
    path("users/create/", views.UserCreateView.as_view(), name="user_create"),
    path("users/<uuid:pk>/edit/", views.UserUpdateView.as_view(), name="user_edit"),
    path("users/<uuid:pk>/delete/", views.UserDeleteView.as_view(), name="user_delete"),
    path("users/<uuid:pk>/toggle/", views.user_toggle, name="user_toggle"),
    path("users/<uuid:pk>/reinitialiser/", views.user_send_reset, name="user_send_reset"),
    path("users/<uuid:pk>/consulter/", views.impersonate_start, name="impersonate_start"),
    path("consulter/stop/", views.impersonate_stop, name="impersonate_stop"),

    path("ai-monitoring/", views.AiMonitoringView.as_view(), name="ai_monitoring"),
    path("ai-prompt/", views.AiPromptView.as_view(), name="ai_prompt"),

    path("integrations/", views.IntegrationsView.as_view(), name="integrations"),
    path("integrations/<slug:code>/test/", views.integrations_test, name="integrations_test"),

    path("sms/", views.SmsView.as_view(), name="sms"),
    path("sms/test/<slug:code>/", views.sms_test, name="sms_test"),
    path("sms/modeles/<int:pk>/modifier/", views.SmsTemplateUpdateView.as_view(), name="sms_template_edit"),
    path("sms/modeles/<int:pk>/supprimer/", views.SmsTemplateDeleteView.as_view(), name="sms_template_delete"),
]
