from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.urls import reverse
from companies.models import Company
from billing.models import Plan, Subscription
from ai.models import AiDraftEntry
from django.contrib.auth import get_user_model

User = get_user_model()

class BackofficeAdminTests(TestCase):
    def setUp(self):
        # Création d'un utilisateur staff et d'un utilisateur normal
        self.admin_user = User.objects.create_superuser(
            username='admin', email='admin@rrs.fr', password='password123', is_staff=True
        )
        self.normal_user = User.objects.create_user(
            username='user', email='user@rrs.fr', password='password123', is_staff=False
        )
        
        # Données de test
        self.company = Company.objects.create(
            denomination="Test Corp", 
            siren="123456789", 
            owner=self.normal_user
        )
        self.plan = Plan.objects.create(name="Pro", price_eur=49)
        self.subscription = Subscription.objects.create(
            user=self.normal_user, 
            plan=self.plan, 
            status='active'
        )
        self.draft = AiDraftEntry.objects.create(
            company=self.company, 
            status='validated'
        )

    def test_dashboard_access_staff(self):
        """L'utilisateur staff doit accéder au dashboard."""
        self.client.login(username='admin', password='password123')
        response = self.client.get(reverse('admin_backoffice:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tableau de Bord Administrateur")

    def test_dashboard_access_denied_non_staff(self):
        """L'utilisateur non-staff doit être redirigé ou bloqué."""
        self.client.login(username='user', password='password123')
        response = self.client.get(reverse('admin_backoffice:dashboard'))
        # Django UserPassesTestMixin redirige vers login ou renvoie 403
        self.assertIn(response.status_code, [302, 403])

    def test_companies_list_access(self):
        """L'admin doit voir la liste des entreprises."""
        self.client.login(username='admin', password='password123')
        response = self.client.get(reverse('admin_backoffice:companies_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Corp")

    def test_subscriptions_list_access(self):
        """L'admin doit voir la liste des abonnements."""
        self.client.login(username='admin', password='password123')
        response = self.client.get(reverse('admin_backoffice:subscriptions_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pro")

    def test_ai_monitoring_stats(self):
        """Les statistiques de l'IA doivent être correctes."""
        self.client.login(username='admin', password='password123')
        response = self.client.get(reverse('admin_backoffice:ai_monitoring'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1") # Total drafts

    def test_ai_prompt_access(self):
        """L'admin doit pouvoir accéder à la page du prompt."""
        self.client.login(username='admin', password='password123')
        response = self.client.get(reverse('admin_backoffice:ai_prompt'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Personnalisation de l'IA")
