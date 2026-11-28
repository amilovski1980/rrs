#!/bin/bash
# Installation complete Road Runner Solutions sur VPS Ubuntu (root).
# Idempotent : peut etre relance sans casser l'existant.
set -euo pipefail

DOMAIN="${DOMAIN:-rrsolutions.io}"
WWW="www.${DOMAIN}"
APP_DIR=/srv/rrs/app
APP_USER=rrs
DB_NAME=rrs
DB_USER=rrs

echo "== 1. Paquets systeme =="
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip python3-dev \
  nginx postgresql postgresql-contrib certbot python3-certbot-nginx git curl ufw build-essential libpq-dev >/dev/null

echo "== 2. Pare-feu =="
ufw allow OpenSSH >/dev/null || true
ufw allow "Nginx Full" >/dev/null || true
ufw --force enable >/dev/null || true

echo "== 3. Utilisateur applicatif =="
id -u "$APP_USER" >/dev/null 2>&1 || adduser --system --group --home /srv/rrs "$APP_USER"

echo "== 4. Code =="
mkdir -p /srv/rrs
if [ -f "$APP_DIR/manage.py" ] && [ ! -d "$APP_DIR/.git" ]; then
    echo "   code deja deployee (archive) — mise a jour manuelle si besoin"
elif [ ! -d "$APP_DIR/.git" ]; then
    rm -rf "$APP_DIR"
    sudo -u "$APP_USER" git clone https://github.com/amilovski1980/rrs.git "$APP_DIR"
else
    cd "$APP_DIR"
    sudo -u "$APP_USER" git fetch origin >/dev/null || true
    sudo -u "$APP_USER" git checkout -f main -- 2>/dev/null || true
    sudo -u "$APP_USER" git pull --ff-only origin main || true
fi
chown -R "$APP_USER:$APP_USER" /srv/rrs
cd "$APP_DIR"

echo "== 5. Environnement Python =="
[ -d .venv ] || sudo -u "$APP_USER" python3 -m venv .venv
sudo -u "$APP_USER" .venv/bin/pip install --quiet --upgrade pip
sudo -u "$APP_USER" .venv/bin/pip install --quiet -r requirements.txt

echo "== 6. Base PostgreSQL =="
DB_PASSWORD_FILE=/srv/rrs/db_password
if [ ! -f "$DB_PASSWORD_FILE" ]; then
    openssl rand -hex 24 > "$DB_PASSWORD_FILE"
    chmod 600 "$DB_PASSWORD_FILE"
fi
DB_PASSWORD=$(cat "$DB_PASSWORD_FILE")
sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';"
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"
sudo -u postgres psql -c "ALTER USER $DB_USER WITH PASSWORD '$DB_PASSWORD';" >/dev/null

echo "== 7. Fichier .env =="
SECRET_FILE=/srv/rrs/secret_key
if [ ! -f "$SECRET_FILE" ]; then
    openssl rand -hex 50 > "$SECRET_FILE"
    chmod 600 "$SECRET_FILE"
fi
SECRET_KEY=$(cat "$SECRET_FILE")

cat > "$APP_DIR/.env" <<ENVFILE
SECRET_KEY=$SECRET_KEY
DEBUG=0
ALLOWED_HOSTS=$DOMAIN,$WWW,127.0.0.1
CSRF_TRUSTED_ORIGINS=https://$DOMAIN,https://$WWW
SITE_BASE_URL=https://$DOMAIN
DATABASE_URL=postgres://$DB_USER:$DB_PASSWORD@127.0.0.1:5432/$DB_NAME
ENVFILE
chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
chmod 600 "$APP_DIR/.env"

echo "== 8. Migrations + statiques =="
sudo -u "$APP_USER" .venv/bin/python manage.py migrate --no-input
sudo -u "$APP_USER" .venv/bin/python manage.py collectstatic --no-input --clear >/dev/null

echo "== 9. Service systemd =="
cat > /etc/systemd/system/rrs.service <<'UNIT'
[Unit]
Description=Road Runner Solutions (Django + Gunicorn)
After=network.target postgresql.service
Wants=postgresql.service

[Service]
User=rrs
Group=rrs
WorkingDirectory=/srv/rrs/app
EnvironmentFile=/srv/rrs/app/.env
ExecStart=/srv/rrs/app/.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3 --timeout 90 --access-logfile - --error-logfile -
Restart=always
RestartSec=3
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable rrs >/dev/null 2>&1 || true
systemctl restart rrs
sleep 3
systemctl is-active rrs

echo "== 10. Nginx =="
cat > /etc/nginx/sites-available/rrs <<NGINX
server {
    listen 80;
    server_name $DOMAIN $WWW;
    client_max_body_size 12m;
    location /static/ { alias $APP_DIR/staticfiles/; expires 30d; add_header Cache-Control "public"; }
    location /media/ { alias $APP_DIR/media/; expires 7d; }
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
NGINX
ln -sf /etc/nginx/sites-available/rrs /etc/nginx/sites-enabled/rrs
rm -f /etc/nginx/sites-enabled/default
nginx -t >/dev/null && systemctl reload nginx

echo "== 11. HTTPS (si le DNS pointe deja vers ce serveur) =="
if certbot --nginx -d "$DOMAIN" -d "$WWW" --non-interactive --agree-tos -m "admin@$DOMAIN" --redirect >/dev/null 2>&1; then
    echo "HTTPS OK"
else
    echo "HTTPS en attente du DNS (relancer: certbot --nginx -d $DOMAIN -d $WWW --redirect)"
fi

echo "== 12. Sauvegardes =="
cp "$APP_DIR/deploy/backup.sh" /srv/rrs/backup.sh
chmod +x /srv/rrs/backup.sh
( crontab -l 2>/dev/null | grep -v rrs/backup.sh || true; echo "30 3 * * * /srv/rrs/backup.sh >> /var/log/rrs-backup.log 2>&1" ) | crontab -

echo "== 13. Verification locale =="
curl -s -o /dev/null -w "gunicorn HTTP %{http_code}\n" -H "Host: $DOMAIN" http://127.0.0.1:8000/compte/ || true

echo "INSTALLATION TERMINEE pour $DOMAIN"
