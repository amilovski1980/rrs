#!/usr/bin/env bash
# Sync des assets Django vers docs/assets (servis par Vercel via rewrites /static → /assets).
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p docs/assets

cp -f static/css/app.css docs/assets/app.css
cp -f static/js/app.js docs/assets/app.js
cp -f static/js/grok-voice.js docs/assets/grok-voice.js
cp -f \
  static/img/logo.png \
  static/img/logo-48.png \
  static/img/logo-96.png \
  static/img/logo-192.png \
  docs/assets/

# Contrôles minimaux (échoue le build si un fichier manque ou diverge)
for f in app.css app.js grok-voice.js logo.png logo-48.png logo-96.png logo-192.png; do
  test -f "docs/assets/$f"
done
cmp -s static/css/app.css docs/assets/app.css
cmp -s static/js/app.js docs/assets/app.js
cmp -s static/js/grok-voice.js docs/assets/grok-voice.js

echo "vercel_build: docs/assets synchronisé ($(wc -c < docs/assets/app.css) o app.css)"
