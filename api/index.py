"""WSGI handler pour Vercel Python serverless.

Au démarrage à froid : base SQLite temporaire, migrations puis seed de la
société de démonstration. Toutes les données vivent dans /tmp (éphémère).
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("DJANGO_DEBUG", "0")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/demo.sqlite3")
os.environ.setdefault(
    "ALLOWED_HOSTS",
    ".vercel.app,localhost,127.0.0.1,rrs-sandy.vercel.app",
)
os.environ.setdefault(
    "CSRF_TRUSTED_ORIGINS", "https://rrs-sandy.vercel.app,https://*.vercel.app"
)
os.environ.setdefault("SESSION_ENGINE", "django.contrib.sessions.backends.signed_cookies")

import django  # noqa: E402

django.setup()

from django.core.management import call_command  # noqa: E402

call_command("migrate", verbosity=0, interactive=False)

try:
    from core.demo import seed_demo

    seed_demo()
except Exception:  # la démo doit rester disponible même si le seed échoue
    pass

from django.core.wsgi import get_wsgi_application  # noqa: E402

app = get_wsgi_application()
