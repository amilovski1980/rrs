"""Construit la configuration Django à partir d'une URL de base.

Le pooler Neon (PgBouncer) n'accepte pas les curseurs côté serveur.
Les hôtes Neon et Vercel exigent TLS ; un Postgres local ne l'exige pas.
"""
from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse


def database_from_url(url: str) -> dict:
    if url.startswith("postgres"):
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        host = parsed.hostname or ""
        if "sslmode" in query:
            sslmode = query["sslmode"][-1]
        elif host.endswith(".neon.tech") or "pooler" in host or host.endswith(".vercel-storage.com"):
            sslmode = "require"
        else:
            sslmode = ""
        config = {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote((parsed.path or "").lstrip("/")),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": host or "localhost",
            "PORT": parsed.port or 5432,
            "CONN_MAX_AGE": 0,
            "DISABLE_SERVER_SIDE_CURSORS": True,
        }
        if sslmode:
            config["OPTIONS"] = {"sslmode": sslmode}
        return config
    if url.startswith("sqlite"):
        # sqlite:////tmp/demo.sqlite3 → /tmp/demo.sqlite3
        path = "/" + url.replace("sqlite:", "").lstrip("/")
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": path or "/tmp/demo.sqlite3",
        }
    raise ValueError("URL de base non reconnue")
