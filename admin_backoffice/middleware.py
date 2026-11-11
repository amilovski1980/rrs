from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from .models import SiteConfiguration

class DynamicConfigMiddleware:
    """
    Middleware qui synchronise les paramètres de Django avec la base de données
    à chaque requête. Permet de changer SMTP et API Keys sans redémarrer.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 1. Vérification du Mode Maintenance
        try:
            config, _ = SiteConfiguration.objects.get_or_create(id=1)
            
            # Mise à jour dynamique des settings Django
            from django.conf import settings
            
            # SMTP
            settings.EMAIL_HOST = config.smtp_host
            settings.EMAIL_PORT = config.smtp_port
            settings.EMAIL_HOST_USER = config.smtp_user
            settings.EMAIL_HOST_PASSWORD = config.smtp_password
            settings.DEFAULT_FROM_EMAIL = config.email_from
            
            # API Keys
            settings.STRIPE_SECRET_KEY = config.stripe_secret_key
            settings.LLM_API_KEY = config.llm_api_key
            settings.INSEE_API_KEY = config.insee_api_key
            
            # Site
            settings.SITE_NAME = config.site_name
            
            # Blocage si mode maintenance actif (sauf pour les admins)
            if config.maintenance_mode and not request.user.is_staff:
                return HttpResponseForbidden("<h1>Site en Maintenance</h1><p>Nous revenons très vite !</p>")
                
        except Exception as e:
            # On ne bloque pas le site si la config échoue, on utilise les defaults de settings.py
            print(f"DynamicConfigMiddleware Error: {e}")

        return self.get_response(request)
