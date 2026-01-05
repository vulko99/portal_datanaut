from pathlib import Path
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "django-insecure-%ndk%m=r^+t_i&$1s@-&tw@x2zcqu&w^zfwm_r6#(tc=%am&0b"

DEBUG = True

ALLOWED_HOSTS = [
    ".pythonanywhere.com",
    "datanaut.space",
    "www.datanaut.space",
    "portal.datanaut.space",
    "127.0.0.1",
    "localhost",
]

# ако по-късно знаем точния адрес в pythonanywhere (примерно yourname.pythonanywhere.com),
# ще го сложим и в CSRF_TRUSTED_ORIGINS
CSRF_TRUSTED_ORIGINS = [
    "https://datanaut.space",
    "https://www.datanaut.space",
    "https://portal.datanaut.space",
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.humanize",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",          # нужно за allauth

    "landing",                      # маркетинг сайт
    "portal",                       # клиентски портал

    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.openid_connect",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",  # важно за allauth
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "datanaut_site.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",  # нужно за allauth
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "portal.context_processors.acting_access_context",
            ],
        },
    },
]

WSGI_APPLICATION = "datanaut_site.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
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

# ---------- I18N / ЕЗИЦИ ----------

LANGUAGE_CODE = "en"

LANGUAGES = [
    ("en", _("English")),
    ("bg", _("Bulgarian")),
    ("de", _("German")),
]

LOCALE_PATHS = [
    BASE_DIR / "locale",
]

TIME_ZONE = "UTC"

USE_I18N = True
USE_TZ = True

# ---------- STATIC ----------

STATIC_URL = "/static/"
# тук ще отидат всички събрани статични файлове при collectstatic
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- FILES / MEDIA (за качените договори) ---
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------- EMAIL / CONTACT ----------

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "no-reply@datanaut.local"

CONTACT_NOTIFY_EMAIL = "your.email@example.com"  # може да го смениш по-късно

# ---------- AUTH / PORTАЛ / SSO ----------

# django.contrib.sites
SITE_ID = 1

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

# ВАЖНО: ползваме името "login" (без namespace)
LOGIN_REDIRECT_URL = 'portal:dashboard'
LOGIN_URL = 'portal_login'          # име на view-то, което ползваш за login
LOGOUT_REDIRECT_URL = 'portal_login'

# Настройки на allauth (development-friendly)
ACCOUNT_LOGIN_METHODS = {"email", "username"}

ACCOUNT_SIGNUP_FIELDS = [
    "email*",
    "username*",
    "password1*",
    "password2*",
]

ACCOUNT_EMAIL_VERIFICATION = "none"   # за dev; в production ще го направим "mandatory"
ACCOUNT_LOGOUT_ON_GET = True

# Засега не конфигурираме конкретен OpenID Connect provider – това ще е по-късно,
# когато знаем клиента (Azure AD, Okta и т.н.)

# SOCIALACCOUNT_PROVIDERS = {...}
