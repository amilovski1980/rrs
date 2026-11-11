"""
Settings de base. Les variantes dev/prod (config/settings_dev.py, settings_prod.py)
héritent de ce module.
"""
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path):
    """Mini chargeur .env sans dépendance : ne surcharge pas les vars déjà définies."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k.strip(), v)


_load_dotenv(BASE_DIR / ".env")

env = os.environ

SECRET_KEY = env.get("DJANGO_SECRET_KEY", "dev-only-change-me")
DEBUG = env.get("DJANGO_DEBUG", "").lower() in ("1", "true", "yes")
ALLOWED_HOSTS = env.get("ALLOWED_HOSTS", "").split(",")
if not ALLOWED_HOSTS or ALLOWED_HOSTS == [""]:
    ALLOWED_HOSTS = [".vercel.app", "localhost", "127.0.0.1"]
else:
    if ".vercel.app" not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(".vercel.app")


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # internes
    "accounts",
    "companies",
    "accounting",
    "documents",
    "ai",
    "integrations",
    "billing",
    "admin_backoffice",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # tenant isolation (middleware custom a S1)
    "core.tenancy.TenantMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "config" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context.selected_company",
            ],
        },
    },
]

DATABASE_URL = env.get("DATABASE_URL", "")

if DATABASE_URL.startswith("postgres"):
    # Parsing minimal de postgresql://user:pass@host:port/dbname
    from urllib.parse import urlparse, unquote

    u = urlparse(DATABASE_URL)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(u.path.lstrip("/")),
            "USER": unquote(u.username or ""),
            "PASSWORD": unquote(u.password or ""),
            "HOST": u.hostname or "localhost",
            "PORT": u.port or 5432,
        }
    }
elif DATABASE_URL.startswith("sqlite"):
    # Serverless / CI : base SQLite temporaire (ex. sqlite:////tmp/demo.sqlite3)
    path = "/" + DATABASE_URL.replace("sqlite:", "").lstrip("/")
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": path or "/tmp/demo.sqlite3",
        }
    }
else:
    # Local sans Postgres : SQLite de secours (migrations OK, RLS non fonctionnelle)
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

# Sessions signées en cookie : stateless, tolère le serverless (pas de table sessions).
SESSION_ENGINE = env.get(
    "SESSION_ENGINE", "django.contrib.sessions.backends.signed_cookies"
)

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"
    },
}
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Modèle user custom (sans mot de passe)
AUTH_USER_MODEL = "accounts.User"

# --- Intégrations ---
INPI_TOKEN = env.get("INPI_TOKEN", "")
API_ENTREPRISE_TOKEN = env.get("API_ENTREPRISE_TOKEN", "")

# LLM self-hosté AminiA(vLLM en API OpenAI-compatible)
LLM_BASE_URL = env.get("LLM_BASE_URL", "http://localhost:8000/v1")
LLM_MODEL = env.get("LLM_MODEL", "qwen3-32b-awq")
LLM_API_KEY = env.get("LLM_API_KEY", "not-needed-for-vllm-local")

# Stripe (abonnements clients)
STRIPE_SECRET_KEY = env.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = env.get("STRIPE_WEBHOOK_SECRET", "")

# Email de connexion (dev : fichier EMAIL_FILE_PATH ; prod : Brevo, Postal…)
if env.get("EMAIL_BACKEND"):
    EMAIL_BACKEND = env.get("EMAIL_BACKEND")
elif DEBUG:
    EMAIL_BACKEND = "django.core.mail.backends.filebased.EmailBackend"
    EMAIL_FILE_PATH = BASE_DIR / "email_outbox"
    EMAIL_FILE_PATH.mkdir(exist_ok=True)
else:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_PORT = int(env.get("EMAIL_PORT", "587"))
    EMAIL_HOST = env.get("EMAIL_HOST", "")
    EMAIL_HOST_USER = env.get("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = env.get("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = env.get("EMAIL_USE_TLS", "1") == "1"
DEFAULT_FROM_EMAIL = env.get("DEFAULT_FROM_EMAIL", "no-reply@roadrunner-solutions.fr")
SITE_NAME = "Road Runner Solutions"
LOGIN_URL = "/compte/"


# --- Déploiement (Render / Railway / VPS) ---
CSRF_TRUSTED_ORIGINS = [
    "https://rrs-sandy.vercel.app",
] + [
    o.strip() for o in env.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    X_FRAME_OPTIONS = "DENY"
    LOGGING = {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {"console": {"class": "logging.StreamHandler"}},
        "root": {"handlers": ["console"], "level": "INFO"},
    }

# --- API Sirene INSEE (api.insee.fr/api-sirene/3.11) ---
INSEE_API_KEY = env.get("INSEE_API_KEY", "")
INSEE_CLIENT_ID = env.get("INSEE_CLIENT_ID", "")
INSEE_CLIENT_SECRET = env.get("INSEE_CLIENT_SECRET", "")
INSEE_TOKEN = env.get("INSEE_TOKEN", "")  # jeton direct (dev/tests)
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "roadrunner",
    }
}

# --- Agent vocal Aminia (SIP / VoIP) ---
VOICE_SIP_HOST = env.get("VOICE_SIP_HOST", "")
VOICE_SIP_WS_PATH = env.get("VOICE_SIP_WS_PATH", "/ws")
VOICE_SIP_WS_PORT = env.get("VOICE_SIP_WS_PORT", "5060")
VOICE_SIP_EXT = env.get("VOICE_SIP_EXT", "2000")      # poste affiché
VOICE_SIP_USER = env.get("VOICE_SIP_USER", "2000")         # identifiant SIP (ex. 20000)
VOICE_SIP_PASSWORD = env.get("VOICE_SIP_PASSWORD", "")
VOICE_SIP_CALLEE = env.get("VOICE_SIP_CALLEE", "9999")  # poste appelé
VOICE_AGENT_NAME = env.get("VOICE_AGENT_NAME", "Aminia")

# Agent vocal Grok (xAI Realtime). La clé reste sur le serveur :
# le navigateur ne reçoit qu'un jeton éphémère.
XAI_API_KEY = env.get("XAI_API_KEY", "")
XAI_VOICE_MODEL = env.get("XAI_VOICE_MODEL", "grok-voice-latest")
XAI_VOICE = env.get("XAI_VOICE", "eve")

