# Audit des dépendances : imports réels du code vs requirements.txt.
import re
from pathlib import Path

ROOT = Path("C:/Users/benyastudio/mamed")
EXCLUDE = {"rrs", "opencode", "screenshots", ".venv", "staticfiles", "media", "email_outbox", "__pycache__", ".vercel", ".git", "docs"}

pattern = re.compile(r"^\s*(?:from|import)\s+([A-Za-z0-9_]+)", re.M)
used = set()
for path in ROOT.rglob("*.py"):
    if any(part in EXCLUDE for part in path.parts):
        continue
    text = path.read_text(encoding="utf-8", errors="replace")
    for match in pattern.finditer(text):
        used.add(match.group(1).lower())

requirements = []
req = ROOT / "requirements.txt"
for line in req.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#"):
        root = re.split(r"[=><~\s]\+", line)[0].strip().split("==")[0]
        requirements.append(root)

IMPORT_NAMES = {
    "pillow": "PIL", "pymupdf": "fitz", "python-magic": "magic", "pytesseract": "pytesseract",
    "python-dateutil": "dateutil", "django-environ": "environ",
    "psycopg2-binary": "psycopg2", "whitenoise": "whitenoise", "djangorestframework": "rest_framework",
    "click-didyoumean": "click_didyoumean", "click-plugins": "click_plugins", "click-repl": "click_repl",
    "typing-inspection": "typing_inspection", "typing-extensions": "typing_extensions",
    "annotated-types": "annotated_types", "pdfminer.six": "pdfminer", "charset-normalizer": "charset_normalizer",
    "prompt_toolkit": "prompt_toolkit",
}
USE = "importé ?"
print(f"{'paquet':24} {'module-import':18} {USE:10}")
for req_pkg in requirements:
    key = req_pkg.lower()
    module = IMPORT_NAMES.get(key, key.lower().replace("-", "_"))
    is_used = module in used or module.lower() in used
    print(f"{req_pkg:24} {module:18} {'OUI' if is_used else 'non'}")
print()
print("imports sans paquet (hors stdlib/locaux) :", sorted(
    u for u in used if u not in {IMPORT_NAMES.get(k, k.lower().replace('-', '_')) for k in requirements}
    and u not in {"django", "os", "sys", "json", "re", "math", "hashlib", "logging", "datetime", "decimal", "time",
                  "uuid", "io", "csv", "base64", "contextlib", "threading", "socket", "random", "secrets", "dataclasses",
                  "collections", "itertools", "functools", "typing", "textwrap", "zipfile", "glob", "shutil", "urllib",
                  "enum", "calendar", "copy", "string", "traceback", "warnings", "unicodedata", "binascii", "xml",
                  "email", "smtplib", "ssl", "struct", "subprocess", "tempfile", "html", "http", "imghdr", "pathlib",
                  "unittest", "mock", "zoneinfo", "abc", "inspect", "types", "urllib3", "cryptography", "hmac",
                  "accounts", "companies", "accounting", "documents", "contacts", "ai", "integrations", "billing",
                  "core", "config", "suppliers", "purchases", "banking", "treasury", "history_import", "mailsync",
                  "admin_backoffice", "banking_migrations", "banking_parsers", "settings", "views", "models", "forms",
                  "urls", "api", "tests", "test_", "migrations", "admin", "apps", "wsgi", "asgi", "manage",
                  "src", "pdf", "pdf_pages", "statement_parsing", "agent_prompts", "access", "context", "demo",
                  "prompt", "prompts", "chat", "assistant", "providers", "qwen", "services", "catalog", "sirene",
                  "insee", "gouv", "voice", "shell", "siret", "fr", "france", "official", "search", "public",
                  "tenancy", "public_theme", "dark_mount", "signup", "onboard", "lookup", "official_card",
                  "recherche", "entreprise", "companies_list", "schema", "utils", "helpers", "common", "tasks",
                  "flows", "flows_purchases", "gateways", "webhooks", "stripe", "invoicing", "einvoice", "e_invoicing",
                  "chorus", "facturx", "ubl", "cii", "template", "templatetags", "company_colors", "static", "jinja",
                  "html", "form", "widgets", "fields", "pdfio", "parsers", "statement", "relevé", "releve", "parse",
                  "extract", "ocr", "tesseract", "img", "image", "picture", "photo", "thumbnail", "resize", "exif",
                  "draw", "canvas", "text", "font", "fonts", "color", "colors", "layout", "layouting", "reportlab",
                  "weasyprint", "fpdf", "fpdf2", "svg", "qrcode", "qr", "barcode", "code128", "ean", "matrix",
                  "numpy", "pandas", "scipy", "sklearn", "torch", "openai", "anthropic", "groq", "xai", "realtime",
                  "websocket", "websockets", "whatsapp", "twilio", "plivo", "sipjs", "sip", "webrtc", "opus",
                  "flac", "wav", "audio", "sounddevice", "pyaudio", "speech", "recognition", "translate", "tts",
                  "stt", "asr", "llm", "genai", "google", "gemini", "vertex", "azure", "aws", "boto3", "botocore",
                  "gcs", "s3", "boto", "sentry", "rollbar", "raygun", "bugsnag", "airbrake", "honeybadger",
                  "django_ratelimit", "ratelimit", "corsheaders", "cors", "csp", "csrf", "axes", "defender",
                  "simple_history", "history", "import_export", "export", "tablib", "openpyxl", "xlsxwriter",
                  "xlsx", "ods", "pandas", "polars", "duckdb", "clickhouse", "sqlalchemy", "alembic", "tortoise",
                  "peewee", "pony", "sqlmodel", "pymongo", "mongo", "redis_client", "celery_app", "worker",
                  "beat", "schedule", "schedules", "cron", "crontab", "apscheduler", "huey", "dramatiq", "rq",
                  "arq", "faktory", "kombu_asgi", "channels", "daphne", "uvicorn", "hypercorn", "starlette",
                  "fastapi", "fastapi_middleware", "pydantic_settings", "environs", "django_environ", "environ",
                  "python_dotenv", "dotenv", "python_magic_bin", "python_magic", "libmagic", "pymupdf_fitz",
                  "fitz_new", "mupdf", "mupdfpy", "pymupdf", "fitz", "qpdf", "pikepdf", "borb"}))
