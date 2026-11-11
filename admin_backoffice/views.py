from django.views.generic import TemplateView, ListView, UpdateView, CreateView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Sum, Count, Q
from django.shortcuts import redirect, render
from django.http import HttpResponse
from django.contrib import messages
from django.urls import reverse_lazy
from accounts.models import User
from companies.models import Company
from billing.models import Subscription, Plan
from ai.models import AiDraftEntry
from .models import SiteConfiguration, SystemLog
from .forms import SiteConfigurationForm, CompanyAdminForm, PlanAdminForm, SubscriptionAdminForm, UserAdminForm

class AdminStaffMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Mixin pour restreindre l'accès au personnel administratif."""
    def test_func(self):
        return self.request.user.is_staff

# --- DASHBOARD ---
class DashboardView(TemplateView):
    template_name = 'admin_backoffice/dashboard.html'

    def get(self, request, *args, **kwargs):
        try:
            return super().get(request, *args, **kwargs)
        except Exception as e:
            return HttpResponse(f"CRASH DashboardView: {str(e)}", status=500)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['total_users'] = 0
        context['total_companies'] = 0
        context['mrr'] = 0
        context['subs_past_due'] = 0
        context['ai_validation_rate'] = 0
        context['total_ai_drafts'] = 0
        context['recent_companies'] = []
        context['recent_logs'] = []
        return context

# --- CONFIGURATION ---
class SiteSettingsView(AdminStaffMixin, TemplateView):
    template_name = 'admin_backoffice/settings.html'

    def get(self, request):
        config, created = SiteConfiguration.objects.get_or_create(id=1)
        form = SiteConfigurationForm(instance=config)
        return self.render_to_response(self.template_name, {'form': form, 'config': config})

    def post(self, request):
        config, created = SiteConfiguration.objects.get_or_create(id=1)
        form = SiteConfigurationForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, "Configuration mise à jour avec succès !")
            return redirect('admin_backoffice:settings')
        messages.error(request, "Erreur lors de la mise à jour de la configuration.")
        return self.render_to_response(self.template_name, {'form': form, 'config': config})

# --- CRUD COMPANIES ---
class CompanyListView(AdminStaffMixin, ListView):
    model = Company
    template_name = 'admin_backoffice/companies_list.html'
    context_object_name = 'companies'
    paginate_by = 20

class CompanyCreateView(AdminStaffMixin, CreateView):
    model = Company
    form_class = CompanyAdminForm
    template_name = 'admin_backoffice/company_form.html'
    success_url = reverse_lazy('admin_backoffice:companies')

class CompanyUpdateView(AdminStaffMixin, UpdateView):
    model = Company
    form_class = CompanyAdminForm
    template_name = 'admin_backoffice/company_form.html'
    success_url = reverse_lazy('admin_backoffice:companies')

class CompanyDeleteView(AdminStaffMixin, DeleteView):
    model = Company
    template_name = 'admin_backoffice/confirm_delete.html'
    success_url = reverse_lazy('admin_backoffice:companies')

# --- CRUD PLANS ---
class PlanListView(AdminStaffMixin, ListView):
    model = Plan
    template_name = 'admin_backoffice/plans_list.html'
    context_object_name = 'plans'

class PlanCreateView(AdminStaffMixin, CreateView):
    model = Plan
    form_class = PlanAdminForm
    template_name = 'admin_backoffice/plan_form.html'
    success_url = reverse_lazy('admin_backoffice:plans')

class PlanUpdateView(AdminStaffMixin, UpdateView):
    model = Plan
    form_class = PlanAdminForm
    template_name = 'admin_backoffice/plan_form.html'
    success_url = reverse_lazy('admin_backoffice:plans')

class PlanDeleteView(AdminStaffMixin, DeleteView):
    model = Plan
    template_name = 'admin_backoffice/confirm_delete.html'
    success_url = reverse_lazy('admin_backoffice:plans')

# --- CRUD SUBSCRIPTIONS ---
class SubscriptionListView(AdminStaffMixin, ListView):
    model = Subscription
    template_name = 'admin_backoffice/subscriptions_list.html'
    context_object_name = 'subscriptions'
    paginate_by = 20

class SubscriptionCreateView(AdminStaffMixin, CreateView):
    model = Subscription
    form_class = SubscriptionAdminForm
    template_name = 'admin_backoffice/subscription_form.html'
    success_url = reverse_lazy('admin_backoffice:subscriptions')

class SubscriptionUpdateView(AdminStaffMixin, UpdateView):
    model = Subscription
    form_class = SubscriptionAdminForm
    template_name = 'admin_backoffice/subscription_form.html'
    success_url = reverse_lazy('admin_backoffice:subscriptions')

class SubscriptionDeleteView(AdminStaffMixin, DeleteView):
    model = Subscription
    template_name = 'admin_backoffice/confirm_delete.html'
    success_url = reverse_lazy('admin_backoffice:subscriptions')

# --- CRUD USERS ---
class UserListView(AdminStaffMixin, ListView):
    model = User
    template_name = 'admin_backoffice/users_list.html'
    context_object_name = 'users'
    paginate_by = 20

class UserUpdateView(AdminStaffMixin, UpdateView):
    model = User
    form_class = UserAdminForm
    template_name = 'admin_backoffice/user_form.html'
    success_url = reverse_lazy('admin_backoffice:users')

class UserDeleteView(AdminStaffMixin, DeleteView):
    model = User
    template_name = 'admin_backoffice/confirm_delete.html'
    success_url = reverse_lazy('admin_backoffice:users')

# --- LOGS & AI ---
class SystemLogsView(AdminStaffMixin, ListView):
    model = SystemLog
    template_name = 'admin_backoffice/logs.html'
    context_object_name = 'logs'
    paginate_by = 50

class AiMonitoringView(AdminStaffMixin, TemplateView):
    template_name = 'admin_backoffice/ai_monitoring.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        drafts = AiDraftEntry.objects.all()
        context['total_drafts'] = drafts.count()
        context['validated_count'] = drafts.filter(status='validated').count()
        context['rejected_count'] = drafts.filter(status='rejected').count()
        context['pending_count'] = drafts.filter(status='pending').count()
        context['recent_drafts'] = drafts.order_by('-created_at')[:10]
        return context

class AiPromptView(AdminStaffMixin, TemplateView):
    template_name = 'admin_backoffice/ai_prompt.html'

    def get(self, request):
        from django.conf import settings
        prompt = getattr(settings, 'AI_SYSTEM_PROMPT', 'You are a professional accountant...')
        return self.render_to_response(self.template_name, {'current_prompt': prompt})

    def post(self, request):
        new_prompt = request.POST.get('prompt')
        return redirect('admin_backoffice:ai_prompt')
