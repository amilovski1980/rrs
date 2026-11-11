#!/bin/sh
# Sync static Django → docs/assets (Vercel sert /static via rewrite vers /assets).
# POSIX uniquement (pas de bash, cmp, dirname, wc) — image build Vercel minimale.
set -eu

# $0 = scripts/vercel_build.sh (relatif ou absolu) → racine du dépôt
ROOT=${0%/*}/..
cd "$ROOT"

# --- AJOUT : Migration de la base de données ---
echo "vercel_build: Lancement des migrations..."
python manage.py migrate --no-input || echo "Migration failed or skipped (normal if DB not connected during build)"
# ----------------------------------------------

mkdir -p docs/assets

cp -f static/css/app.css docs/assets/app.css
cp -f static/js/app.js docs/assets/app.js
cp -f static/js/grok-voice.js docs/assets/grok-voice.js
cp -f static/img/logo.png docs/assets/logo.png
cp -f static/img/logo-48.png docs/assets/logo-48.png
cp -f static/img/logo-96.png docs/assets/logo-96.png
cp -f static/img/logo-192.png docs/assets/logo-192.png

for f in app.css app.js grok-voice.js logo.png logo-48.png logo-96.png logo-192.png; do
  test -f "docs/assets/$f"
done

echo "vercel_build: docs/assets synchronisé"
