# Déploiement VPS — Road Runner Solutions

Kit prêt dans `deploy/`. Ordre d'exécution sur un VPS Ubuntu 22.04/24.04 neuf.

## 1. Pré-requis serveur
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3-pip nginx postgresql \
  postgresql-contrib certbot python3-certbot-nginx git ufw
sudo ufw allow OpenSSH && sudo ufw allow "Nginx Full" && sudo ufw --force enable
```

## 2. Utilisateur applicatif + code
```bash
sudo adduser --system --group --home /srv/rrs rrs
sudo -u rrs git clone https://github.com/amilovski1980/rrs.git /srv/rrs/app
cd /srv/rrs/app && git checkout main
sudo -u rrs python3.11 -m venv .venv
sudo -u rrs .venv/bin/pip install -r requirements.txt
```

## 3. Base Postgres
```bash
sudo -u postgres psql -c "CREATE USER rrs WITH PASSWORD 'MOT_DE_PASSE_FORT';"
sudo -u postgres psql -c "CREATE DATABASE rrs OWNER rrs;"
```

## 4. Variables d'environnement
```bash
sudo -u rrs cp deploy/env.example /srv/rrs/app/.env
sudo -u rrs nano /srv/rrs/app/.env   # remplir les valeurs
```
Renseigner au minimum : `SECRET_KEY`, `DEBUG=0`, `ALLOWED_HOSTS=mondomaine.fr,www.mondomaine.fr`,
`CSRF_TRUSTED_ORIGINS=https://mondomaine.fr,https://www.mondomaine.fr`,
`DATABASE_URL=postgres://rrs:MOT_DE_PASSE_FORT@127.0.0.1:5432/rrs`,
et les IA (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `XAI_API_KEY`, `ELEVENLABS_API_KEY`).

## 5. Migrations + statiques
```bash
cd /srv/rrs/app
sudo -u rrs .venv/bin/python manage.py migrate --no-input
sudo -u rrs .venv/bin/python manage.py collectstatic --no-input
```

## 6. Service systemd
```bash
sudo cp deploy/rrs.service /etc/systemd/system/rrs.service
sudo systemctl daemon-reload
sudo systemctl enable --now rrs
sudo systemctl status rrs
```

## 7. Nginx + HTTPS
```bash
sudo cp deploy/nginx-rrs.conf /etc/nginx/sites-available/rrs
sudo ln -s /etc/nginx/sites-available/rrs /etc/nginx/sites-enabled/rrs
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d mondomaine.fr -d www.mondomaine.fr
```

## 8. Reprise des données depuis Vercel/Neon
Sur la machine locale (avec l'URL secrète prod) :
```bash
pg_dump "postgres://…url-prod…" --no-owner --format=custom -f rrs-prod.dump
scp rrs-prod.dump vous@vps:/tmp/
```
Sur le VPS :
```bash
sudo -u postgres pg_restore --no-owner -d rrs < /tmp/rrs-prod.dump
```
> Toutes les images (logos, tickets, PDF importés) sont stockées **dans la base** (BinaryField) :
> le dump suffit — aucun dossier média à copier.

## 9. Sauvegardes quotidiennes
```bash
sudo cp deploy/backup.sh /srv/rrs/backup.sh && sudo chmod +x /srv/rrs/backup.sh
sudo crontab -e   # ajouter :
30 3 * * * /srv/rrs/backup.sh >> /var/log/rrs-backup.log 2>&1
```

## 10. Mise à jour applicative
```bash
sudo -u rrs /srv/rrs/app/deploy/update.sh
```

## Vérifications
- `curl -I https://mondomaine.fr/compte/` → 200
- `/admin-backoffice/health/` → ok
- Scan d'un QR : `/v/<id>/` → page de vérification
- Upload d'un ticket photo (OCR 25 s max)
