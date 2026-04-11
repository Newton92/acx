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

echo "✅ Mise à jour terminée !"
systemctl status acx-gunicorn --no-pager
