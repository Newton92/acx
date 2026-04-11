# deploy/gunicorn.conf.py
# Configuration Gunicorn pour ACX en production
#
# Emplacement sur le serveur : /var/www/acx/deploy/gunicorn.conf.py
# Démarrage : gunicorn -c deploy/gunicorn.conf.py acx.wsgi:application

import multiprocessing

# ── Socket UNIX (plus performant qu'un port TCP avec Apache) ──────────────────
bind = "unix:/run/gunicorn/acx.sock"

# ── Workers ────────────────────────────────────────────────────────────────────
# Règle : (2 × nb_CPU) + 1
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"
worker_connections = 1000
timeout = 120
keepalive = 5

# ── Logs ───────────────────────────────────────────────────────────────────────
accesslog = "/var/log/gunicorn/acx-access.log"
errorlog  = "/var/log/gunicorn/acx-error.log"
loglevel  = "info"
capture_output = True

# ── Process ────────────────────────────────────────────────────────────────────
daemon = False           # systemd gère le processus
pidfile = "/run/gunicorn/acx.pid"
user    = "www-data"
group   = "www-data"

# ── Rechargement automatique (désactiver en prod stable) ──────────────────────
reload = False
