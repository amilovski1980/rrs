#!/bin/sh
# Sauvegarde quotidienne Postgres + rotation 14 jours.
# Installé par crontab : 30 3 * * * /srv/rrs/backup.sh
set -eu

DEST=/srv/rrs/backups
mkdir -p "$DEST"
STAMP=$(date +%Y%m%d-%H%M)

sudo -u postgres pg_dump rrs --format=custom -f "$DEST/rrs-$STAMP.dump"
find "$DEST" -name 'rrs-*.dump' -mtime +14 -delete
echo "sauvegarde: $DEST/rrs-$STAMP.dump"
