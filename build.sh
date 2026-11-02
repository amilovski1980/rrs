#!/usr/bin/env bash
# Script de build utilisé par Render / Railway / hébergeurs compatibles.
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate --no-input
