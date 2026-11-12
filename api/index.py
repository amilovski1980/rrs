"""WSGI handler pour Vercel Python serverless.

Au démarrage à froid : migrations puis seed de la démonstration. Si un
démarrage échoue, la première requête rattrape les migrations (robustesse
base Postgres / Neon : le migrate est idempotent).
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

from core.deploy import assurer_migrations  # noqa: E402


def lancer_seed():
    """Seed de la démonstration : échec non bloquant."""
    try:
        from core.demo import seed_demo

        seed_demo()
    except Exception as exc:  # noqa: BLE001
        print(f"[seed] ignoré : {exc}", flush=True)


assurer_migrations()
lancer_seed()

from django.core.wsgi import get_wsgi_application  # noqa: E402

_app_django = get_wsgi_application()


def app(environ, start_response):
    """Point d'entrée WSGI : rattrapage des migrations à la première requête."""
    assurer_migrations()
    return _app_django(environ, start_response)
