from django.views.generic import TemplateView, ListView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Sum, Count, Q
from django.shortcuts import redirect
from django.http import HttpResponse
from accounts.models import User
from companies.models import Company
from billing.models import Subscription, Plan
from ai.models import AiDraftEntry

class AdminStaffMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Mixin pour restreindre l'accès au personnel administratif."""
    def test_func(self):
        return self.request.user.is_staff

class DashboardView(AdminStaffMixin, TemplateView):
    template_name = 'admin_backoffice/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['total_users'] = User.objects.count()
        context['total_companies'] = Company.objects.count()
        active_subs = Subscription.objects.filter(status__in=['active', 'trialing'])
        context['mrr'] = active_subs.aggregate(total=Sum('plan__price_eur'))['total'] or 0
        context['subs_past_due'] = Subscription.objects.filter(status='past_due').count()
        drafts = AiDraftEntry.objects.all()
        total_drafts = drafts.count()
        validated_drafts = drafts.filter(status='validated').count()
        context['ai_validation_rate'] = (validated_drafts / total_drafts * 100) if total_drafts > 0 else 0
        context['total_ai_drafts'] = total_drafts
        context['recent_companies'] = Company.objects.order_by('-created_at')[:5]
        return context

class CompanyListView(AdminStaffMixin, ListView):
    model = Company
    template_name = 'admin_backoffice/companies_list.html'
    context_object_name = 'companies'
    paginate_by = 20

class SubscriptionListView(AdminStaffMixin, ListView):
    model = Subscription
    template_name = 'admin_backoffice/subscriptions_list.html'
    context_object_name = 'subscriptions'
    paginate_by = 20

class PlanListView(AdminStaffMixin, ListView):
    """Gestion des forfaits d'abonnement."""
    model = Plan
    template_name = 'admin_backoffice/plans_list.html'
    context_object_name = 'plans'

class AiMonitoringView(AdminStaffMixin, TemplateView):
    """Analyse détaillée des performances de l'IA."""
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
    """Personnalisation du prompt système de l'IA."""
    template_name = 'admin_backoffice/ai_prompt.html'

    def get(self, request):
        # On récupère le prompt depuis les settings ou un modèle de config
        from django.conf import settings
        prompt = getattr(settings, 'AI_SYSTEM_PROMPT', 'You are a professional accountant...')
        return self.render_to_response(self.template_name, {'current_prompt': prompt})

    def post(self, request):
        new_prompt = request.POST.get('prompt')
        # Note: Dans un vrai environnement, on enregistrerait cela en DB ou via un fichier config.
        # Ici, on simule l'enregistrement.
        return redirect('admin_backoffice:ai_prompt')
