#!/bin/bash
# deploy/install.sh
# Script d'installation complète ACX sur Ubuntu + Apache2 + Gunicorn
#
# Usage (depuis le dossier du projet, en root ou avec sudo) :
#   chmod +x deploy/install.sh
#   sudo bash deploy/install.sh

set -e

# Détecte le dossier réel du projet (là où le script est lancé)
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Détecte automatiquement la version Python disponible (3.12, 3.11, 3.10…)
PYTHON_BIN=$(command -v python3 2>/dev/null || command -v python3.12 || command -v python3.11)
if [ -z "$PYTHON_BIN" ]; then
    echo "ERREUR : Python 3 introuvable."
    exit 1
fi
echo "Python détecté : $PYTHON_BIN ($($PYTHON_BIN --version))"
echo "Dossier projet : $APP_DIR"

echo "=== [1/9] Mise à jour des paquets système ==="
apt-get update -y
apt-get install -y \
    python3 python3-pip python3-venv python3-dev \
    postgresql postgresql-contrib libpq-dev \
    apache2 \
    build-essential libssl-dev libffi-dev \
    libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 shared-mime-info \
    git curl

echo "=== [2/9] Activation des modules Apache ==="
a2enmod proxy proxy_http headers rewrite
systemctl restart apache2

echo "=== [3/9] Vérification du dossier application ==="
# Le dossier existe déjà (projet cloné), on s'assure juste des permissions
chown -R www-data:www-data "$APP_DIR" 2>/dev/null || true

echo "=== [4/9] Création des dossiers de logs Gunicorn ==="
mkdir -p /var/log/gunicorn
chown www-data:www-data /var/log/gunicorn

echo "=== [5/9] Création de l'environnement virtuel Python ==="
cd "$APP_DIR"
if [ ! -d "venv" ]; then
    $PYTHON_BIN -m venv venv
fi
source venv/bin/activate

echo "=== [6/9] Installation des dépendances Python ==="
pip install --upgrade pip
pip install -r requirements.txt

echo "=== [7/9] Vérification du fichier .env ==="
if [ ! -f "$APP_DIR/.env" ]; then
    echo "ERREUR : le fichier .env est manquant !"
    echo "Copiez .env.example → .env et remplissez les vraies valeurs."
    exit 1
fi

echo "=== [8/9] Migrations et collectstatic ==="
export DJANGO_SETTINGS_MODULE=acx.settings_prod
export MPLBACKEND=Agg

# Génère les migrations depuis le code (la prod crée ses propres migrations)
python manage.py makemigrations --no-input
python manage.py migrate --no-input
python manage.py collectstatic --no-input

echo "=== [9/9] Installation du service Gunicorn ==="
# Met à jour le chemin du projet dans le service systemd
sed "s|/var/www/acx|$APP_DIR|g" "$APP_DIR/deploy/acx-gunicorn.service" \
    > /etc/systemd/system/acx-gunicorn.service

systemctl daemon-reload
systemctl enable acx-gunicorn
systemctl start acx-gunicorn

echo "=== Installation du VirtualHost Apache ==="
# Met à jour le chemin du projet dans la config Apache
sed "s|/var/www/acx|$APP_DIR|g" "$APP_DIR/deploy/apache-acx.conf" \
    > /etc/apache2/sites-available/acx.conf
a2ensite acx
systemctl reload apache2

echo ""
echo "✅ PEL, to installation terminée hein !"
echo ""
echo "Prochaines étapes :"
echo "  1. Vérifier : sudo systemctl status acx-gunicorn"
