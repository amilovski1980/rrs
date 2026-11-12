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

    def test_dashboard_users_counter_uses_swapped_model(self):
        """Le compteur utilisateurs doit compter accounts.User, pas auth.User.

        Régression : l'ancien code importait django.contrib.auth.models.User
        (modèle swappé) — le compteur plantait en silence et affichait « ? ».
        """
        User.objects.create_user(email='extra1@rrs.fr')
        User.objects.create_user(email='extra2@rrs.fr')
        self.client.login(email='admin@rrs.fr', password='password123')
        response = self.client.get(reverse('admin_backoffice:dashboard'))
        self.assertEqual(response.status_code, 200)
        attendu = User.objects.count()
        self.assertEqual(response.context['total_users'], attendu)
        self.assertEqual(attendu, 4)  # admin + normal (setUp) + 2 extras

    def test_dashboard_real_trends(self):
        """Tendances réelles : nouveaux 30 j et série quotidienne de 14 jours."""
        self.client.login(email='admin@rrs.fr', password='password123')
        response = self.client.get(reverse('admin_backoffice:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.context['users_nouveaux_30j'], 1)
        serie = response.context['users_series']
        self.assertEqual(len(serie), 14)
        self.assertGreaterEqual(serie[-1]['total'], 2)  # admin + normal créés dans setUp
        maximum = max(point['total'] for point in serie)
        for point in serie:
            attendu = round(point['total'] / maximum * 100) if maximum else 0
            self.assertEqual(point['hauteur'], attendu)

    def test_dashboard_subscription_distribution(self):
        """Répartition des abonnements par statut et MRR cohérents."""
        self.client.login(email='admin@rrs.fr', password='password123')
        response = self.client.get(reverse('admin_backoffice:dashboard'))
        self.assertEqual(response.status_code, 200)
        distribution = {
            statut['code']: statut['total']
            for statut in response.context['subs_par_statut']
        }
        self.assertEqual(distribution.get('active'), 1)
        self.assertEqual(distribution.get('past_due'), 0)
        self.assertContains(response, "Actif")

    def test_dashboard_no_fake_trends(self):
        """Les tendances codées en dur ont disparu du template."""
        self.client.login(email='admin@rrs.fr', password='password123')
        response = self.client.get(reverse('admin_backoffice:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "▲ Stable")
        self.assertNotContains(response, "▲ Croissance")

    def test_dashboard_resilient_when_users_table_fails(self):
        """Une panne de la table utilisateurs n'empêche pas le reste du dashboard."""
        from unittest import mock

        self.client.login(email='admin@rrs.fr', password='password123')
        with mock.patch.object(User, 'objects') as faux_manager:
            faux_manager.filter.side_effect = RuntimeError("table cassée")
            response = self.client.get(reverse('admin_backoffice:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['users_indisponible'])
        self.assertContains(response, "Indisponible")

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


class BackofficeAccessAndSectionsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(email="boss@rrs.fr", is_staff=True, is_superuser=True)
        self.admin.set_password("password123")
        self.admin.save()
        self.client_user = User.objects.create_user(email="client@rrs.fr", phone="0600000000")
        self.client_user.set_password("password123")
        self.client_user.save()
        self.company = Company.objects.create(
            denomination="Atelier Client", siren="111111111", owner=self.client_user, regime="micro",
        )
        self.micro = Plan.objects.create(code="micro", name="Micro", price_eur=29)
        self.pro = Plan.objects.create(code="pro", name="Pro", price_eur=79)
        Subscription.objects.create(user=self.client_user, plan=self.micro, status="active")

    def test_client_cannot_open_admin_pages(self):
        self.client.login(email="client@rrs.fr", password="password123")
        names = [
            "dashboard", "users", "companies", "plans", "subscriptions",
            "settings", "logs", "ai_monitoring", "ai_prompt", "integrations", "sms", "health",
        ]
        for name in names:
            response = self.client.get(reverse(f"admin_backoffice:{name}"))
            self.assertEqual(response.status_code, 403, name)

    def test_anonymous_is_redirected(self):
        response = self.client.get(reverse("admin_backoffice:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/compte/", response["Location"])

    def test_admin_layout_is_not_the_client_sidebar(self):
        self.client.login(email="boss@rrs.fr", password="password123")
        page = self.client.get(reverse("admin_backoffice:dashboard"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Back-office")
        self.assertContains(page, "Forfaits")
        self.assertContains(page, "Consignes de l'agent")
        self.assertNotContains(page, "Ajouter une société")
        self.assertNotContains(page, "Grand livre")
        cockpit = self.client.get("/cockpit/")
        self.assertContains(cockpit, "Ajouter une société")
        self.assertContains(cockpit, "Administration")
        self.assertNotContains(cockpit, "Back-office")

    def test_client_cockpit_has_no_admin_entry(self):
        self.client.login(email="client@rrs.fr", password="password123")
        page = self.client.get("/cockpit/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Ajouter une société")
        self.assertNotContains(page, "/admin-backoffice/")
        self.assertNotContains(page, "Back-office")

    def test_user_search_create_toggle_and_roles(self):
        self.client.login(email="boss@rrs.fr", password="password123")
        User.objects.create_user(email="cache@rrs.fr")
        listed = self.client.get(reverse("admin_backoffice:users"), {"q": "client@rrs.fr", "phone": "0"})
        self.assertContains(listed, "client@rrs.fr")
        self.assertNotContains(listed, "cache@rrs.fr")
        created = self.client.post(reverse("admin_backoffice:user_create"), {
            "email": "nouveau@rrs.fr",
            "phone": "0611111111",
            "phone_verified": "on",
            "is_active": "on",
        })
        self.assertEqual(created.status_code, 302)
        created_user = User.objects.get(email="nouveau@rrs.fr")
        self.assertTrue(created_user.phone_verified)
        self.assertFalse(created_user.has_usable_password())
        toggled = self.client.post(reverse("admin_backoffice:user_toggle", kwargs={"pk": created_user.pk}))
        self.assertEqual(toggled.status_code, 302)
        created_user.refresh_from_db()
        self.assertFalse(created_user.is_active)

    def test_impersonation_is_limited_to_active_clients(self):
        self.client.login(email="boss@rrs.fr", password="password123")
        other_admin = User.objects.create_user(email="autre-admin@rrs.fr", is_staff=True)
        refused = self.client.post(reverse("admin_backoffice:impersonate_start", kwargs={"pk": other_admin.pk}))
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(self.client.session["_auth_user_id"], str(self.admin.pk))
        started = self.client.post(
            reverse("admin_backoffice:impersonate_start", kwargs={"pk": self.client_user.pk}),
            follow=True,
        )
        self.assertEqual(started.status_code, 200)
        self.assertContains(started, "Revenir à l'administration")
        self.assertContains(started, "Ajouter une société")
        blocked = self.client.get(reverse("admin_backoffice:dashboard"))
        self.assertEqual(blocked.status_code, 403)
        stopped = self.client.post(reverse("admin_backoffice:impersonate_stop"), follow=True)
        self.assertEqual(stopped.status_code, 200)
        self.assertEqual(self.client.session["_auth_user_id"], str(self.admin.pk))
        self.assertContains(stopped, "Back-office")

    def test_plan_crud_limits_and_features(self):
        self.client.login(email="boss@rrs.fr", password="password123")
        response = self.client.post(reverse("admin_backoffice:plan_create"), {
            "code": "starter",
            "name": "Starter",
            "price_eur": "19",
            "trial_days": "7",
            "description": "Entrée de gamme",
            "max_companies": "1",
            "max_invoices_month": "",
            "max_ai_requests_month": "20",
            "features_text": "Grand livre\nBalance",
            "is_active": "on",
            "ai_prompt": "",
        })
        self.assertEqual(response.status_code, 302)
        plan = Plan.objects.get(code="starter")
        self.assertEqual(plan.features, ["Grand livre", "Balance"])
        self.assertEqual(plan.max_companies, 1)
        self.assertIsNone(plan.max_invoices_month)
        page = self.client.get(reverse("admin_backoffice:plans"))
        self.assertContains(page, "Starter")
        self.assertContains(page, "Grand livre")

    def test_subscription_edit_uses_uuid(self):
        self.client.login(email="boss@rrs.fr", password="password123")
        sub = Subscription.objects.get(user=self.client_user)
        page = self.client.get(reverse("admin_backoffice:subscription_edit", kwargs={"pk": sub.pk}))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Micro")

    def test_integrations_hide_secrets_and_report_status(self):
        from django.test import override_settings

        self.client.login(email="boss@rrs.fr", password="password123")
        secret = "insee-secret-value-9f3c"
        with override_settings(INSEE_API_KEY=secret, INPI_TOKEN="", LLM_BASE_URL=""):
            page = self.client.get(reverse("admin_backoffice:integrations"))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, secret)
        self.assertContains(page, "9f3c")
        self.assertContains(page, "Non configurée")
        self.assertContains(page, "Disponible sans clé")

    def test_integration_probe_does_not_echo_the_secret(self):
        from unittest import mock

        from admin_backoffice.integrations import probe_insee

        with mock.patch("integrations.insee.InseeClient.get_siren", side_effect=RuntimeError("bad insee-secret-value-9f3c")):
            with mock.patch("admin_backoffice.integrations.insee_material", return_value={
                "api_key": "insee-secret-value-9f3c",
                "token": "",
                "client_id": "",
                "client_secret": "",
                "configured": True,
            }):
                result = probe_insee()
        self.assertNotIn("insee-secret-value-9f3c", result["message"])
        self.assertFalse(result["ok"])

    def test_middleware_does_not_wipe_env_secrets(self):
        from django.conf import settings
        from django.test import override_settings

        self.client.login(email="boss@rrs.fr", password="password123")
        with override_settings(INSEE_API_KEY="clef-env-9f3c"):
            self.client.get(reverse("admin_backoffice:dashboard"))
            self.assertEqual(settings.INSEE_API_KEY, "clef-env-9f3c")

    def test_sms_providers_mask_secrets_and_drive_the_hook(self):
        from admin_backoffice.models import SmsMessage, SmsProviderConfig, SmsSettings
        from admin_backoffice.sms import dispatch_sms

        self.client.login(email="boss@rrs.fr", password="password123")
        page = self.client.get(reverse("admin_backoffice:sms"))
        self.assertContains(page, "OVH")
        self.assertContains(page, "Brevo")
        self.assertContains(page, "Twilio")
        secret = "xkeysib-live-SECRET-77aa"
        saved = self.client.post(reverse("admin_backoffice:sms"), {
            "action": "config",
            "active_provider": "brevo",
            "enabled__brevo": "1",
            "sender__brevo": "RRS",
            "brevo__api_key": secret,
        })
        self.assertEqual(saved.status_code, 302)
        stored = SmsProviderConfig.objects.get(code="brevo")
        self.assertEqual(stored.credentials["api_key"], secret)
        self.assertTrue(stored.enabled)
        self.assertEqual(SmsSettings.objects.get(pk=1).active_provider, "brevo")
        again = self.client.get(reverse("admin_backoffice:sms"))
        self.assertNotContains(again, secret)
        self.assertContains(again, "77aa")
        kept = self.client.post(reverse("admin_backoffice:sms"), {
            "action": "config",
            "active_provider": "brevo",
            "enabled__brevo": "1",
            "sender__brevo": "RRS",
            "brevo__api_key": "",
        })
        self.assertEqual(kept.status_code, 302)
        stored.refresh_from_db()
        self.assertEqual(stored.credentials["api_key"], secret)
        tested = self.client.post(reverse("admin_backoffice:sms_test", kwargs={"code": "brevo"}), follow=True)
        self.assertContains(tested, "pas encore branché")
        self.assertNotContains(tested, secret)
        entry = dispatch_sms(recipient="+33601020304", body="Bonjour", actor=self.admin)
        self.assertEqual(entry.status, "skipped")
        self.assertIn("Brevo", entry.detail)
        self.assertTrue(SmsMessage.objects.filter(pk=entry.pk).exists())

    def test_prompt_editor_saves_global_and_plan_layers(self):
        from admin_backoffice.agent_prompts import layers_for_user

        self.client.login(email="boss@rrs.fr", password="password123")
        page = self.client.get(reverse("admin_backoffice:ai_prompt"))
        self.assertContains(page, "Personnalisation de l'IA")
        self.assertContains(page, "volontairement limité")
        self.assertContains(page, "le plus complet")
        custom_global = "Consigne générale de test unique."
        custom_micro = "Micro test : ne parle que du grand livre."
        posted = self.client.post(reverse("admin_backoffice:ai_prompt"), {
            "prompt": custom_global,
            f"plan_prompt_{self.micro.pk}": custom_micro,
            f"plan_prompt_{self.pro.pk}": "",
        }, follow=True)
        self.assertContains(posted, custom_global)
        self.assertContains(posted, custom_micro)
        layers = layers_for_user(self.client_user)
        self.assertEqual(layers[0], custom_global)
        self.assertEqual(layers[1], custom_micro)
        self.micro.refresh_from_db()
        self.assertEqual(self.micro.ai_prompt, custom_micro)
