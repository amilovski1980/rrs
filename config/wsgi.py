import os
from django.core.wsgi import get_wsgi_application
from django.core.management import call_command
from django.contrib.auth import get_user_model

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# 1. On initialise d'abord l'application pour charger le registre des apps
application = get_wsgi_application()

# 2. On lance l'auto-migration APRÈS l'initialisation
try:
    call_command('migrate', interactive=False)
    
    # --- CRÉATION ADMIN TEMPORAIRE ---
    User = get_user_model()
    if not User.objects.filter(email="admin@rrs.com").exists():
        User.objects.create_superuser(
            email="admin@rrs.com", 
            username="admin", 
            password="Yahkouba2026"
        )
        print("✅ Superuser admin@rrs.com créé avec succès.")
    # --------------------------------
    
except Exception as e:
    print(f"Vercel Auto-Migration Error: {e}")
