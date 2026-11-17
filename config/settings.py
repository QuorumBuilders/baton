"""Django settings for Baton, configured through environment variables."""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load local configuration while preserving existing process environment values.
load_dotenv(BASE_DIR / ".env", override=False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY.strip():
    raise ImproperlyConfigured(
        "Set DJANGO_SECRET_KEY in the environment. See .env.example and README.md."
    )

debug_value = os.environ.get("DJANGO_DEBUG", "False").strip().lower()
if debug_value not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
    raise ImproperlyConfigured(
        "DJANGO_DEBUG must be true/false, 1/0, yes/no or on/off."
    )
DEBUG = debug_value in {"true", "1", "yes", "on"}

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core.apps.CoreConfig",
    "accounts.apps.AccountsConfig",
    "patients.apps.PatientsConfig",
]

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["accounts.backends.AccountBackend"]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:dashboard"
LOGOUT_REDIRECT_URL = "core:landing"

# Django's username check does not recognize conditional uniqueness. The database
# enforces every non-empty username; AccountBackend excludes vendors from this lookup.
SILENCED_SYSTEM_CHECKS = ["auth.W004"]


def positive_environment_integer(name, default):
    try:
        value = int(os.environ.get(name, default))
    except ValueError as error:
        raise ImproperlyConfigured(f"{name} must be a positive integer.") from error
    if value <= 0:
        raise ImproperlyConfigured(f"{name} must be a positive integer.")
    return value


OTP_TTL_SECONDS = positive_environment_integer("OTP_TTL_SECONDS", 300)
OTP_MAX_ATTEMPTS = positive_environment_integer("OTP_MAX_ATTEMPTS", 5)
OTP_RESEND_COOLDOWN_SECONDS = positive_environment_integer("OTP_RESEND_COOLDOWN_SECONDS", 60)
OTP_DELIVERY_BACKEND = os.environ.get(
    "OTP_DELIVERY_BACKEND", "accounts.delivery.ConsoleOTPBackend" if DEBUG else ""
)

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

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

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        # SQLite has no row locks. Acquire the writer lock before transaction reads
        # so concurrent confirmations serialize rather than upgrade read locks.
        "OPTIONS": {"transaction_mode": "IMMEDIATE", "timeout": 20},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en"
TIME_ZONE = "Africa/Lagos"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Local HTTP development works with DEBUG=True; production cookies require HTTPS.
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
