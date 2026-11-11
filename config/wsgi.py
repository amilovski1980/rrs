import os
from django.core.wsgi import get_wsgi_application
from django.core.management import call_command

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# 1. On initialise d'abord l'application pour charger le registre des apps
application = get_wsgi_application()

# 2. On lance l'auto-migration APRÈS l'initialisation
try:
    # On utilise call_command pour s'assurer que les tables existent
    call_command('migrate', interactive=False)
except Exception as e:
    # On log l'erreur mais on ne bloque pas le démarrage
    print(f"Vercel Auto-Migration Error: {e}")
