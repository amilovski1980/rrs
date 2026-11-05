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
    def test_vercel_json_is_valid_and_within_limits(self):
        self.assertTrue(VERCEL_JSON.is_file())
        data = json.loads(VERCEL_JSON.read_text(encoding="utf-8"))

        for key in ("buildCommand", "installCommand", "outputDirectory"):
            val = data.get(key)
            self.assertIsInstance(val, str, msg=f"{key} doit être une string")
            self.assertLessEqual(
                len(val),
                MAX_CMD,
                msg=f"{key} trop long ({len(val)} > {MAX_CMD})",
            )
            self.assertTrue(val.strip(), msg=f"{key} vide")

        self.assertEqual(data["outputDirectory"], "docs")
        self.assertEqual(data["buildCommand"], "sh scripts/vercel_build.sh")

        rewrites = data.get("rewrites") or []
        self.assertTrue(rewrites)
        sources = {r.get("source") for r in rewrites}
        self.assertIn("/static/css/app.css", sources)
        self.assertIn("/static/img/:path*", sources)
        self.assertIn("/(.*)", sources)

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
        self.assertNotIn("pipefail", text)
        self.assertNotIn("cmp ", text)
        self.assertNotRegex(text, r"(^|\n)bash\b")
        # Shebang POSIX
        self.assertTrue(text.startswith("#!/bin/sh") or text.startswith("#!/usr/bin/sh"))
