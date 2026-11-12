"""Tests de configuration déploiement (Vercel)."""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
VERCEL_JSON = ROOT / "vercel.json"
BUILD_SCRIPT = ROOT / "scripts" / "vercel_build.sh"

# Limites schema Vercel (champs string courants)
MAX_CMD = 256


class VercelConfigTests(SimpleTestCase):
    def test_vercel_json_runs_django_and_migrate_on_deploy(self):
        """Le site servi est l'application Django, et le build lance migrate.

        outputDirectory=docs remplacerait le back-office par le site statique.
        """
        self.assertTrue(VERCEL_JSON.is_file())
        data = json.loads(VERCEL_JSON.read_text(encoding="utf-8"))
        command = data.get("buildCommand")
        self.assertIsInstance(command, str)
        self.assertLessEqual(len(command), MAX_CMD)
        self.assertEqual(command, "sh scripts/vercel_build.sh")
        self.assertNotIn("outputDirectory", data)

        included = data["functions"]["api/index.py"]["includeFiles"]
        for needle in ("admin_backoffice/**", "billing/**", "accounts/**", "core/**"):
            self.assertIn(needle, included)
        destinations = [route.get("dest") for route in data["routes"]]
        self.assertIn("api/index.py", destinations)

    def test_runtime_entrypoint_retries_migrations(self):
        text = (ROOT / "api" / "index.py").read_text(encoding="utf-8")
        self.assertIn("from core.deploy import assurer_migrations", text)
        self.assertIn("assurer_migrations()", text)

    def test_known_backoffice_migrations_are_in_the_repo(self):
        from core.deploy import KNOWN_MIGRATIONS

        for app_label, name in KNOWN_MIGRATIONS:
            path = ROOT / app_label / "migrations" / f"{name}.py"
            self.assertTrue(path.is_file(), path)

    def test_database_url_parser(self):
        from config.dburl import database_from_url

        neon = database_from_url(
            "postgresql://user:p%40ss@ep-example-pooler.eu-west-1.aws.neon.tech:5432/neondb"
        )
        self.assertEqual(neon["HOST"], "ep-example-pooler.eu-west-1.aws.neon.tech")
        self.assertEqual(neon["PASSWORD"], "p@ss")
        self.assertEqual(neon["OPTIONS"]["sslmode"], "require")
        self.assertTrue(neon["DISABLE_SERVER_SIDE_CURSORS"])

        local = database_from_url("postgres://user:secret@localhost:5432/roadrunner")
        self.assertNotIn("OPTIONS", local)
        self.assertEqual(local["NAME"], "roadrunner")

        sqlite = database_from_url("sqlite:////tmp/demo.sqlite3")
        self.assertEqual(sqlite["NAME"], "/tmp/demo.sqlite3")

    def test_vercel_build_script_exists_and_is_executable(self):
        self.assertTrue(BUILD_SCRIPT.is_file())
        self.assertTrue(
            BUILD_SCRIPT.stat().st_mode & 0o111,
            msg="scripts/vercel_build.sh doit être exécutable",
        )
        text = BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("set -eu", text)
        self.assertIn("docs/assets", text)
        self.assertIn("static/css/app.css", text)
        self.assertIn("manage.py migrate", text)
        self.assertNotIn("pipefail", text)
        self.assertNotIn("cmp ", text)
        self.assertNotRegex(text, r"(^|\n)bash\b")
        # Shebang POSIX
        self.assertTrue(text.startswith("#!/bin/sh") or text.startswith("#!/usr/bin/sh"))
