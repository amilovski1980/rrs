#!/bin/sh
# Mise à jour de l'application sur le VPS : git pull, deps, migrations,
# statiques, redémarrage. Usage : sudo -u rrs /srv/rrs/app/deploy/update.sh
set -eu

cd /srv/rrs/app

echo "→ git pull"
git pull --ff-only origin main

echo "→ dépendances Python"
.venv/bin/pip install --quiet -r requirements.txt

echo "→ migrations"
.venv/bin/python manage.py migrate --no-input

echo "→ fichiers statiques"
.venv/bin/python manage.py collectstatic --no-input --clear

echo "→ redémarrage du service"
sudo systemctl restart rrs

echo "✓ Application à jour"
