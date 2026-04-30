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

echo "=== [3b/5] Seed des rôles ==="
python manage.py shell -c "
from accounts.models import Role
roles = [(1,'Personnel entreprise'),(2,'Personnel ACREMAC'),(3,'Administrateur entreprise'),(4,'Administrateur'),(5,'Responsable Pays')]
for rid, name in roles:
    obj, created = Role.objects.get_or_create(id=rid)
    if created: print(f'  → Rôle {rid} ({name}) créé')
    else: print(f'  → Rôle {rid} ({name}) déjà présent')
"

echo "=== [4/5] Collectstatic ==="
python manage.py collectstatic --no-input

echo "=== [5/5] Redémarrage Gunicorn ==="
systemctl restart acx-gunicorn

echo "=== Gestion du cron job poll_mail ==="
# Désactive le timer systemd si activé (on utilise cron à la place)
if systemctl is-active --quiet acx-poll-mail.timer 2>/dev/null; then
    systemctl stop acx-poll-mail.timer
    systemctl disable acx-poll-mail.timer 2>/dev/null || true
    echo "  → Timer systemd désactivé (on utilise /etc/cron.d/)"
fi

# Toujours recréer le fichier cron (mise à jour du chemin si APP_DIR a changé)
mkdir -p /var/log/acx
cat > /etc/cron.d/acx-poll-mail << EOF
# ACX — Polling IMAP des boîtes mail des tenants (toutes les 5 minutes)
DJANGO_SETTINGS_MODULE=acx.settings_prod
MPLBACKEND=Agg

*/5 * * * * www-data $APP_DIR/venv/bin/python $APP_DIR/manage.py poll_mail >> /var/log/acx/poll-mail.log 2>&1
EOF
chmod 644 /etc/cron.d/acx-poll-mail
echo "  → Cron mis à jour : /etc/cron.d/acx-poll-mail"

echo "✅ Pel, ta mise à jour terminée hein!"
systemctl status acx-gunicorn --no-pager
