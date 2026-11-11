import os
from django.core.wsgi import get_wsgi_application
from django.core.management import call_command

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Auto-migration pour Vercel : force la création des tables au démarrage du worker
try:
    # On utilise call_command pour s'assurer que les tables existent
    # Cela ne prend que quelques millisecondes si les migrations sont déjà faites
    call_command('migrate', interactive=False)
except Exception as e:
    # On log l'erreur mais on ne bloque pas le démarrage
    print(f"Vercel Auto-Migration Error: {e}")

application = get_wsgi_application()
