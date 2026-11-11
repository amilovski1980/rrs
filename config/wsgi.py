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
    
    # --- FORCE ADMIN ACCESS ---
    User = get_user_model()
    user, created = User.objects.get_or_create(
        email="admin@rrs.com", 
        defaults={"username": "admin"}
    )
    # On force le mot de passe à chaque démarrage pour être sûr
    user.set_password("Yahkouba2026")
    user.is_superuser = True
    user.is_staff = True
    user.save()
    print(f"✅ Admin access forced for admin@rrs.com")
    # ---------------------------
    
except Exception as e:
    print(f"Vercel Auto-Migration Error: {e}")
