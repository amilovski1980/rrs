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
        # Le modèle User du projet n'a pas de champ username et n'implémente pas create_superuser.
        self.admin_user = User.objects.create_user(
            email='admin@rrs.fr', is_staff=True, is_superuser=True
        )
        self.admin_user.set_password('password123')
        self.admin_user.save()
        self.normal_user = User.objects.create_user(
            email='user@rrs.fr', is_staff=False
        )
        self.normal_user.set_password('password123')
        self.normal_user.save()
        
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
        self.client.login(email='admin@rrs.fr', password='password123')
        response = self.client.get(reverse('admin_backoffice:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tableau de Bord Administrateur")

    def test_dashboard_url_alias_access(self):
        """L'alias dashboard_url doit pointer vers la même vue."""
        self.client.login(email='admin@rrs.fr', password='password123')
        response = self.client.get(reverse('admin_backoffice:dashboard_url'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tableau de Bord Administrateur")

    def test_dashboard_access_denied_non_staff(self):
        """L'utilisateur non-staff doit être redirigé ou bloqué."""
        self.client.login(email='user@rrs.fr', password='password123')
        response = self.client.get(reverse('admin_backoffice:dashboard'))
        # Django UserPassesTestMixin redirige vers login ou renvoie 403
        self.assertIn(response.status_code, [302, 403])

    def test_companies_list_access(self):
        """L'admin doit voir la liste des entreprises via le nom canonique."""
        self.client.login(email='admin@rrs.fr', password='password123')
        response = self.client.get(reverse('admin_backoffice:companies'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Corp")

    def test_companies_list_alias_access(self):
        """L'alias companies_list doit pointer vers la même vue."""
        self.client.login(email='admin@rrs.fr', password='password123')
        response = self.client.get(reverse('admin_backoffice:companies_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Corp")

    def test_subscriptions_list_access(self):
        """L'admin doit voir la liste des abonnements via le nom canonique."""
        self.client.login(email='admin@rrs.fr', password='password123')
        response = self.client.get(reverse('admin_backoffice:subscriptions'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pro")

    def test_subscriptions_list_alias_access(self):
        """L'alias subscriptions_list doit pointer vers la même vue."""
        self.client.login(email='admin@rrs.fr', password='password123')
        response = self.client.get(reverse('admin_backoffice:subscriptions_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pro")

    def test_plans_list_alias_access(self):
        """L'alias plans_list doit pointer vers la même vue."""
        self.client.login(email='admin@rrs.fr', password='password123')
        response = self.client.get(reverse('admin_backoffice:plans_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pro")

    def test_dashboard_template_resolves_all_urls(self):
        """Le dashboard ne doit lever aucune erreur de reverse (NoReverseMatch)."""
        self.client.login(email='admin@rrs.fr', password='password123')
        # Une 500 indiquerait typiquement un {% url %} cassé dans le template.
        response = self.client.get(reverse('admin_backoffice:dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_ai_monitoring_stats(self):
        """Les statistiques de l'IA doivent être correctes."""
        self.client.login(email='admin@rrs.fr', password='password123')
        response = self.client.get(reverse('admin_backoffice:ai_monitoring'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1") # Total drafts

    def test_ai_prompt_access(self):
        """L'admin doit pouvoir accéder à la page du prompt."""
        self.client.login(email='admin@rrs.fr', password='password123')
        response = self.client.get(reverse('admin_backoffice:ai_prompt'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Personnalisation de l'IA")

    def test_ai_prompt_update(self):
        """L'admin doit pouvoir mettre à jour le prompt système."""
        self.client.login(email='admin@rrs.fr', password='password123')
        new_prompt = "Tu es un expert-comptable français."
        response = self.client.post(
            reverse('admin_backoffice:ai_prompt'),
            {'prompt': new_prompt},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, new_prompt)

    def test_company_edit_url_uuid(self):
        """L'URL d'édition d'une société doit accepter un UUID."""
        self.client.login(email='admin@rrs.fr', password='password123')
        response = self.client.get(
            reverse('admin_backoffice:company_edit', kwargs={'pk': self.company.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Corp")

    def test_company_delete_url_uuid(self):
        """L'URL de suppression d'une société doit accepter un UUID."""
        self.client.login(email='admin@rrs.fr', password='password123')
        response = self.client.get(
            reverse('admin_backoffice:company_delete', kwargs={'pk': self.company.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Corp")
