#!/bin/bash
# deploy/update.sh
# Script de mise à jour de l'application en production
#
# Usage :
#   sudo bash deploy/update.sh

set -e
APP_DIR="/var/www/html/acx"

echo "=== [1/5] Pull git ==="
cd $APP_DIR
git pull origin main

echo "=== [2/5] Mise à jour des dépendances ==="
source venv/bin/activate
pip install -r requirements.txt

echo "=== [3/5] Migrations ==="
export DJANGO_SETTINGS_MODULE=acx.settings_prod
export MPLBACKEND=Agg
python manage.py makemigrations --no-input
python manage.py migrate --no-input

echo "=== [4/5] Collectstatic ==="
python manage.py collectstatic --no-input

echo "=== [5/5] Redémarrage Gunicorn ==="
systemctl restart acx-gunicorn

echo "=== Vérification du cron job poll_mail ==="
if [ ! -f /etc/cron.d/acx-poll-mail ]; then
    echo "  → Cron manquant, recréation…"
    mkdir -p /var/log/acx
    cat > /etc/cron.d/acx-poll-mail << EOF
# ACX — Polling IMAP des boîtes mail des tenants (toutes les 5 minutes)
DJANGO_SETTINGS_MODULE=acx.settings_prod
MPLBACKEND=Agg

*/5 * * * * www-data $APP_DIR/venv/bin/python $APP_DIR/manage.py poll_mail >> /var/log/acx/poll-mail.log 2>&1
EOF
    chmod 644 /etc/cron.d/acx-poll-mail
    echo "  → Cron recréé : /etc/cron.d/acx-poll-mail"
else
    echo "  → Cron déjà présent : /etc/cron.d/acx-poll-mail"
fi

echo "✅ Pel, ta mise à jour terminée hein!"
systemctl status acx-gunicorn --no-pager
