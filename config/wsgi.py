import os
from django.core.wsgi import get_wsgi_application
from django.core.management import call_command

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Auto-migration pour Vercel
try:
    call_command('migrate', interactive=False)
except Exception as e:
    print(f"Migration error: {e}")

application = get_wsgi_application()
