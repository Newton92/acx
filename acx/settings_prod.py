"""
Settings de PRODUCTION pour ACX.

Utilisation :
    export DJANGO_SETTINGS_MODULE=acx.settings_prod

Toutes les valeurs sensibles sont lues depuis le fichier .env
(via django-environ). Copiez .env.example → .env sur le serveur
et remplissez les valeurs réelles.
"""

# ── Matplotlib : backend sans GUI (évite l'erreur "No module named 'tkinter'") ──
import matplotlib
matplotlib.use("Agg")

import environ
from pathlib import Path
from datetime import timedelta

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)

# Charge le fichier .env situé à la racine du projet
environ.Env.read_env(BASE_DIR / ".env")

# ── Sécurité ───────────────────────────────────────────────────────────────────
SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")

# ── Applications ───────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    "rest_framework",
    "corsheaders",
    "rest_framework.authtoken",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",

    "accounts",
    "tenancy",
    "cases",
    "customers",
    "collections_management",
    "treasury_management",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "acx.urls"
WSGI_APPLICATION = "acx.wsgi.application"
AUTH_USER_MODEL = "accounts.User"

# ── Templates ──────────────────────────────────────────────────────────────────
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ── Base de données ────────────────────────────────────────────────────────────
DATABASES = {
    "default": env.db("DATABASE_URL")
    # Format : postgres://USER:PASSWORD@HOST:PORT/DBNAME
}

# ── CORS ───────────────────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS")

# ── DRF ────────────────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
    ],
}

# ── JWT ────────────────────────────────────────────────────────────────────────
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME":  timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS":  True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# ── Fichiers statiques & médias ────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ── Internationalisation ───────────────────────────────────────────────────────
LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Africa/Ndjamena"
USE_I18N = True
USE_TZ = True

# ── Validateurs de mots de passe ───────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ── Email ──────────────────────────────────────────────────────────────────────
# Utilise l'API HTTP SendGrid (port 443) pour contourner le blocage SMTP du VPS.
# Fallback SMTP conservé si EMAIL_PROVIDER != "sendgrid".
_email_provider = env("EMAIL_PROVIDER", default="sendgrid")

if _email_provider == "sendgrid":
    INSTALLED_APPS += ["anymail"]
    EMAIL_BACKEND = "anymail.backends.sendgrid.EmailBackend"
    ANYMAIL = {
        "SENDGRID_API_KEY": env("SENDGRID_API_KEY", default=""),
    }
else:
    EMAIL_BACKEND = "core.email_backend.InsecureEmailBackend"
    EMAIL_HOST = env("EMAIL_HOST", default="3.236.213.114")
    EMAIL_PORT = env.int("EMAIL_PORT", default=587)
    EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
    EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=False)
    EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="acx@acremac.com")
    EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")

DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="acx@acremac.com")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# ── URLs frontaux ──────────────────────────────────────────────────────────────
FRONTEND_BASE_URL = env("FRONTEND_BASE_URL", default="https://acx-acremac.net")
FRONTEND_CLIENT_PORTAL_BASE_URL = env("FRONTEND_CLIENT_PORTAL_BASE_URL", default="https://acx-acremac.net/fr")

# ── Limites upload ─────────────────────────────────────────────────────────────
ACX_CP_MAX_FILE_MB = 10
ACX_CP_MAX_TOTAL_MB = 20

# ── Modèles ACX ───────────────────────────────────────────────────────────────
ACX_TENANT_MODEL = "tenancy.Tenant"
ACX_PORTFOLIO_MODEL = "cases.Portfolio"
ACX_DEBTOR_MODEL = "customers.Customer"

# ── Sécurité HTTPS (à activer une fois le SSL en place) ───────────────────────
# SECURE_HSTS_SECONDS = 31536000
# SECURE_HSTS_INCLUDE_SUBDOMAINS = True
# SECURE_SSL_REDIRECT = True
# SESSION_COOKIE_SECURE = True
# CSRF_COOKIE_SECURE = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
