import logging

from django.views.generic import TemplateView, ListView, UpdateView, CreateView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Sum, Count, Q
from django.shortcuts import redirect, render
from django.http import HttpResponse
from django.contrib import messages
from django.urls import reverse_lazy
from django.utils import timezone
from accounts.models import User
from companies.models import Company
from billing.models import Subscription, Plan
from ai.models import AiDraftEntry
from .models import SiteConfiguration, SystemLog
from .forms import SiteConfigurationForm, CompanyAdminForm, PlanAdminForm, SubscriptionAdminForm, UserAdminForm

logger = logging.getLogger(__name__)


def _variation_pourcent(actuelle, precedente):
    """Variation entre deux périodes, en %. None s'il n'y a pas de base de comparaison."""
    if precedente <= 0:
        return None
    return round((actuelle - precedente) / precedente * 100)


def _serie_quotidienne(queryset, champ_date, jours, maintenant=None):
    """Compte journalier d'un queryset sur les N derniers jours (barres CSS sans librairie)."""
    maintenant = maintenant or timezone.now()
    serie = []
    for decalage in range(jours - 1, -1, -1):
        debut = (maintenant - timezone.timedelta(days=decalage)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        fin = debut + timezone.timedelta(days=1)
        total = queryset.filter(
            **{f'{champ_date}__gte': debut, f'{champ_date}__lt': fin}
        ).count()
        serie.append({'label': debut.strftime('%d/%m'), 'total': total})
    maximum = max((point['total'] for point in serie), default=0)
    for point in serie:
        point['hauteur'] = round(point['total'] / maximum * 100) if maximum else 0
    return serie


class AdminStaffMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Mixin pour restreindre l'accès au personnel administratif."""
    def test_func(self):
        return self.request.user.is_staff

# --- DASHBOARD ---
class DashboardView(AdminStaffMixin, TemplateView):
    """Tableau de bord : indicateurs réels, tendances 30 j et graphique 14 j.

    Chaque famille d'indicateurs est isolée : un échec est journalisé et le
    reste du tableau de bord s'affiche quand même (état « indisponible »
    explicite, jamais un masquage silencieux).
    """
    template_name = 'admin_backoffice/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        maintenant = timezone.now()
        limite_30j = maintenant - timezone.timedelta(days=30)
        limite_60j = maintenant - timezone.timedelta(days=60)

        context.update({
            'total_users': '—',
            'users_nouveaux_30j': None,
            'users_variation': None,
            'users_series': [],
            'total_companies': '—',
            'companies_nouveaux_30j': None,
            'companies_variation': None,
            'mrr': '—',
            'mrr_abonnements': None,
            'subs_past_due': 0,
            'subs_par_statut': [],
            'ai_validation_rate': '—',
            'total_ai_drafts': '—',
            'ai_pending_drafts': '—',
            'recent_companies': [],
            'recent_logs': [],
        })

        # Utilisateurs — modèle swappé du projet : accounts.User.
        # (L'ancien code importait django.contrib.auth.models.User : avec le
        # modèle personnalisé ce compteur levait une AttributeError masquée et
        # affichait « ? » en permanence.)
        try:
            nouveaux_30j = User.objects.filter(created_at__gte=limite_30j).count()
            nouveaux_precedents = User.objects.filter(
                created_at__gte=limite_60j, created_at__lt=limite_30j
            ).count()
            context.update({
                'total_users': User.objects.count(),
                'users_nouveaux_30j': nouveaux_30j,
                'users_variation': _variation_pourcent(nouveaux_30j, nouveaux_precedents),
                'users_series': _serie_quotidienne(User.objects, 'created_at', 14, maintenant),
            })
        except Exception as exc:
            logger.error("Dashboard : indicateurs utilisateurs indisponibles : %s", exc)
            context['users_indisponible'] = True

        # Sociétés
        try:
            societes_30j = Company.objects.filter(created_at__gte=limite_30j).count()
            societes_precedentes = Company.objects.filter(
                created_at__gte=limite_60j, created_at__lt=limite_30j
            ).count()
            context.update({
                'total_companies': Company.objects.count(),
                'recent_companies': Company.objects.order_by('-created_at')[:5],
                'companies_nouveaux_30j': societes_30j,
                'companies_variation': _variation_pourcent(societes_30j, societes_precedentes),
            })
        except Exception as exc:
            logger.error("Dashboard : indicateurs sociétés indisponibles : %s", exc)
            context['companies_indisponible'] = True

        # Facturation : MRR réel + répartition par statut
        try:
            abonnements_actifs = Subscription.objects.filter(status__in=['active', 'trialing'])
            mrr_val = abonnements_actifs.aggregate(total=Sum('plan__price_eur'))['total'] or 0
            par_statut = {
                ligne['status']: ligne['total']
                for ligne in Subscription.objects.values('status').annotate(total=Count('id'))
            }
            context.update({
                'mrr': f"{mrr_val:,.2f} €",
                'mrr_abonnements': abonnements_actifs.count(),
                'subs_past_due': par_statut.get('past_due', 0),
                'subs_par_statut': [
                    {'code': code, 'label': label, 'total': par_statut.get(code, 0)}
                    for code, label in Subscription.STATUSES
                ],
            })
        except Exception as exc:
            logger.error("Dashboard : indicateurs facturation indisponibles : %s", exc)
            context['facturation_indisponible'] = True

        # IA
        try:
            drafts = AiDraftEntry.objects.all()
            total = drafts.count()
            valides = drafts.filter(status='validated').count()
            context.update({
                'ai_validation_rate': f"{(valides / total * 100):.1f}%" if total > 0 else "0%",
                'total_ai_drafts': total,
                'ai_pending_drafts': drafts.filter(status='pending').count(),
            })
        except Exception as exc:
            logger.error("Dashboard : indicateurs IA indisponibles : %s", exc)
            context['ia_indisponible'] = True

        # Journal système
        try:
            context['recent_logs'] = SystemLog.objects.all().order_by('-timestamp')[:10]
        except Exception as exc:
            logger.error("Dashboard : journal système indisponible : %s", exc)
            context['logs_indisponible'] = True

        return context

# --- CONFIGURATION ---
class SiteSettingsView(AdminStaffMixin, TemplateView):
    template_name = 'admin_backoffice/settings.html'

    def get_context_data(self, **kwargs):
        """Prépare le formulaire et la configuration courante pour le template."""
        context = super().get_context_data(**kwargs)
        config, _ = SiteConfiguration.objects.get_or_create(id=1)
        context['config'] = config
        context['form'] = SiteConfigurationForm(instance=config)
        return context

    def post(self, request, *args, **kwargs):
        """Valide et sauvegarde la configuration du site."""
        config, _ = SiteConfiguration.objects.get_or_create(id=1)
        form = SiteConfigurationForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, "Configuration mise à jour avec succès !")
            return redirect('admin_backoffice:settings')
        messages.error(request, "Erreur lors de la mise à jour de la configuration.")
        context = self.get_context_data(**kwargs)
        context['form'] = form
        return self.render_to_response(context)

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

    def get_context_data(self, **kwargs):
        """Injecte le prompt système actuel dans le contexte du template."""
        context = super().get_context_data(**kwargs)
        from django.conf import settings
        context['current_prompt'] = getattr(
            settings, 'AI_SYSTEM_PROMPT', 'You are a professional accountant...'
        )
        return context

    def post(self, request, *args, **kwargs):
        """Met à jour le prompt système puis redirige vers la page de configuration."""
        from django.conf import settings
        new_prompt = request.POST.get('prompt')
        if new_prompt is not None:
            settings.AI_SYSTEM_PROMPT = new_prompt.strip()
        return redirect('admin_backoffice:ai_prompt')
