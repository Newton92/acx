# ACX – ACREMAC Collections Experience

ACX est une plateforme SaaS multi-tenant dédiée à la gestion du recouvrement, de la relation client et du pilotage des portefeuilles financiers.

---

## Fonctionnalités principales

- Architecture SaaS multi-tenant avec isolation stricte des données par tenant
- Gestion des rôles et permissions (RBAC) : Personnel, Admin entreprise, Admin ACREMAC, Responsable Pays
- Gestion des portefeuilles, clients, débiteurs et dossiers de recouvrement
- Suivi des actions de recouvrement avec historique d'audit
- **Messagerie entrante (IMAP)** : polling automatique, dispatch vers agents, workflow d'acceptation/réaffectation
- Notifications e-mail HTML lors du dispatch/réaffectation
- Support client avec pièces jointes
- Tableaux de bord et indicateurs clés (KPI)
- Internationalisation (Français / Anglais)

---

## Stack technique

- Python 3.10+
- Django 4.x
- Django REST Framework
- PostgreSQL
- JWT (access / refresh) via `djangorestframework-simplejwt`
- Gunicorn (WSGI production)
- Apache2 (reverse proxy)
- Cron (`/etc/cron.d/`) pour le polling IMAP

---

## Architecture du projet

```
acx/                        # settings, urls racine
accounts/                   # utilisateurs, tenants, rôles, mail entrant
  models.py                 # User, Tenant, Role, MailSource, IncomingMail, ...
  views_mail_config.py      # API mail inbox + config IMAP + cron status
  management/commands/
    poll_mail.py            # commande de polling IMAP (lancée par cron)
  migrations/               # ignoré en git — généré par la prod
portfolios/                 # portefeuilles financiers
debtors/                    # débiteurs
collections/                # dossiers et actions de recouvrement
support/                    # tickets de support
audit/                      # journal d'audit
integrations/               # connecteurs externes
deploy/
  install.sh                # installation initiale (Ubuntu + Apache2 + Gunicorn)
  update.sh                 # mise à jour en production
  acx-gunicorn.service      # service systemd Gunicorn
  apache-acx.conf           # VirtualHost Apache
```

---

## Modèles clés — Mail entrant

### `MailSource`
Boîte IMAP par tenant.

| Champ | Description |
|---|---|
| `tenant` | Tenant propriétaire |
| `host` / `port` | Serveur IMAP |
| `username` / `password` | Identifiants |
| `use_ssl` | SSL/TLS (par tenant) |
| `is_active` | Actif ou non |
| `last_polled_at` | Dernière tentative de polling (mise à jour même en cas d'erreur) |
| `last_error` | Dernier message d'erreur IMAP (vide si succès) |

### `IncomingMail`
Mail reçu et dispatché.

| Champ | Description |
|---|---|
| `source` | MailSource d'origine |
| `subject` / `sender` / `body_text` / `body_html` | Contenu |
| `received_at` | Date/heure de réception |
| `status` | `new` / `dispatched` / `processed` / `ignored` |
| `assigned_to` | Agent assigné |
| `assigned_at` | Date d'assignation |
| `accepted_at` | Date d'acceptation formelle par l'agent |
| `accepted_by` | Agent ayant accepté |
| `dispatch_history` | JSON — historique des dispatches/réaffectations |

---

## API Mail entrant

Base URL : `/api/tenant/mail/`

| Méthode | Endpoint | Description |
|---|---|---|
| GET | `inbox/` | Liste des mails (filtrables, paginés) |
| GET | `inbox/<id>/` | Détail d'un mail |
| POST | `inbox/<id>/dispatch/` | Dispatcher un mail à un agent |
| POST | `inbox/<id>/redispatch/` | Redispatcher |
| POST | `inbox/<id>/self-dispatch/` | S'auto-assigner |
| POST | `inbox/<id>/restore/` | Remettre en `new` |
| POST | `inbox/<id>/process/` | Marquer traité |
| POST | `inbox/<id>/ignore/` | Ignorer |
| POST | `inbox/<id>/accept/` | Accepter formellement (assigné uniquement) |
| POST | `inbox/<id>/reassign/` | Réaffecter à un collègue |
| GET | `config/` | Lire la config IMAP du tenant |
| POST/PUT | `config/` | Créer ou mettre à jour la config IMAP |
| DELETE | `config/` | Supprimer la config IMAP |
| GET | `cron-status/` | État du service de polling (health: ok / stale / error / inactive) |

---

## Commande de polling

```bash
python manage.py poll_mail
```

- Se connecte à toutes les `MailSource` actives
- Respecte le flag `use_ssl` par tenant
- Timeout socket de 30 secondes par connexion
- Met à jour `last_polled_at` et `last_error` même en cas d'erreur IMAP
- Envoie un e-mail HTML de notification à l'agent en cas de dispatch automatique

---

## Cron job (production)

Le polling est exécuté via `/etc/cron.d/acx-poll-mail` (installé automatiquement par `deploy/install.sh`) :

```
*/5 * * * * www-data /var/www/html/acx/venv/bin/python /var/www/html/acx/manage.py poll_mail >> /var/log/acx/poll-mail.log 2>&1
```

Logs : `tail -f /var/log/acx/poll-mail.log`

---

## Installation

### Prérequis système (à installer manuellement)

```bash
apt-get install -y python3 python3-venv python3-pip apache2 libapache2-mod-wsgi-py3
```

> **Note importante** : Ne pas lancer `apt-get upgrade` sans l'accord de l'administrateur réseau. Un upgrade peut réinitialiser les routes réseau configurées manuellement (notamment la route vers `10.0.168.x`).

### Installation automatisée

```bash
chmod +x deploy/install.sh
sudo bash deploy/install.sh
```

Ce script :
1. Active les modules Apache (`proxy`, `proxy_http`, `headers`, `rewrite`)
2. Crée le virtualenv Python et installe les dépendances
3. Lance les migrations et `collectstatic`
4. Installe et démarre le service Gunicorn (`acx-gunicorn`)
5. Configure le VirtualHost Apache
6. Installe le cron job de polling mail

### Mise à jour en production

```bash
sudo bash deploy/update.sh
```

---

## Variables d'environnement (`.env`)

```env
DEBUG=False
SECRET_KEY=your-secret-key
DATABASE_URL=postgres://user:password@localhost:5432/acx
ALLOWED_HOSTS=your-domain.com

# Email sortant (notifications de dispatch)
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=noreply@example.com
EMAIL_HOST_PASSWORD=your-password
DEFAULT_FROM_EMAIL=ACX <noreply@example.com>

# URL du frontend (utilisée dans les liens CTA des e-mails)
FRONTEND_BASE_URL=https://your-frontend.com
```

Copier `.env.example` → `.env` et remplir les valeurs réelles avant de lancer `install.sh`.

---

## Développement local

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

---

## Sécurité

- Authentification JWT (access token court + refresh token)
- Isolation stricte des données par tenant
- RBAC sur toutes les API
- Pas de token/secret dans les commits

---

## Auteur

ACREMAC
