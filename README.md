# ACX – ACREMAC Collections Experience

ACX est une plateforme SaaS multi-tenant dédiée à la gestion du recouvrement, de la relation client et du pilotage des portefeuilles financiers.

## Fonctionnalités principales

- Architecture SaaS multi-tenant avec isolation stricte des données
- Gestion des rôles et permissions (RBAC)
- Gestion des portefeuilles, clients, débiteurs et dossiers
- Suivi des actions de recouvrement
- Support et messagerie avec pièces jointes
- Tableaux de bord et indicateurs clés (KPI)
- Internationalisation (Français / Anglais)

## Stack technique

### Backend
- Django
- Django REST Framework
- PostgreSQL
- JWT (access / refresh)
- Celery + Redis (optionnel)

### Frontend
- Next.js (App Router)
- TypeScript
- Tailwind CSS
- Shadcn UI
- next-intl

## Architecture du projet

### Backend
backend/
- core
- accounts
- tenancy
- portfolios
- debtors
- collections
- support
- audit
- integrations

### Frontend
frontend/
- app/[locale]/(admin)
- app/[locale]/(app)
- app/[locale]/(client)
- src/lib/api
- src/components
- messages (fr.json, en.json)

## Installation

### Backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver

### Frontend
npm install
npm run dev

## Variables d’environnement

Backend (.env)
DEBUG=True
SECRET_KEY=your-secret-key
DATABASE_URL=postgres://user:password@localhost:5432/acx

Frontend (.env.local)
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000/api

## Sécurité
- Authentification JWT
- Refresh automatique des tokens
- Déconnexion sécurisée

## UI & Design
- Design moderne
- Boutons avec icônes
- Couleurs principales :
  - #42210b
  - #ea8c21

## Auteur
ACX – ACREMAC Collections Experience
