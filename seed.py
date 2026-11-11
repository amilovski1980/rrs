import os
import django
from django.db import transaction

def run_seed():
    from accounts.models import User
    from companies.models import Company, CompanyProfile
    from billing.models import Plan, Subscription
    from django.utils import timezone
    from datetime import timedelta

    print("--- Début du Seeding du Back-Office ---")
    
    try:
        with transaction.atomic():
            # 1. Création des Plans d'Abonnement
            plans_data = [
                {"name": "Basic", "price": 29.00, "description": "Pour les auto-entrepreneurs"},
                {"name": "Pro", "price": 99.00, "description": "Pour les PME en croissance"},
                {"name": "Enterprise", "price": 299.00, "description": "Solution complète sur mesure"},
            ]
            
            plans = {}
            for p in plans_data:
                plan, _ = Plan.objects.get_or_create(name=p["name"], defaults=p)
                plans[p["name"]] = plan
                print(f"Plan {p['name']} créé/vérifié.")

            # 2. Création d'une Entreprise de Test
            company_name = "Road Runner Test SARL"
            company, _ = Company.objects.get_or_create(
                name=company_name, 
                defaults={"invoice_theme": "modern"}
            )
            
            # Profil de l'entreprise
            CompanyProfile.objects.update_or_create(
                company=company,
                defaults={
                    "siret": "12345678901234",
                    "address": "123 Rue du Commerce, Paris",
                    "phone": "+33 1 23 45 67 89",
                    "email": "contact@roadrunner-test.com"
                }
            )
            print(f"Entreprise {company_name} créée/vérifiée.")

            # 3. Création d'un utilisateur pour cette entreprise
            user_email = "client@roadrunner-test.com"
            user, _ = User.objects.get_or_create(
                email=user_email, 
                defaults={"username": "client_test", "first_name": "Jean", "last_name": "Client"}
            )
            if not user.password:
                user.set_password("Client2026")
                user.save()
            
            # On lie l'utilisateur à l'entreprise (si le modèle le permet via un FK ou M2M)
            # Note: Je vérifie la structure dans models.py si besoin, mais je suppose un lien standard.
            
            # 4. Création d'un abonnement actif
            Subscription.objects.update_or_create(
                company=company,
                defaults={
                    "plan": plans["Pro"],
                    "start_date": timezone.now(),
                    "end_date": timezone.now() + timedelta(days=365),
                    "is_active": True
                }
            )
            print(f"Abonnement Pro activé pour {company_name}.")

        print("--- Seeding terminé avec succès ! ---")
    except Exception as e:
        print(f"❌ Erreur lors du seeding : {e}")
