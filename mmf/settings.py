import os
from pathlib import Path
from dotenv import load_dotenv

from django.contrib.messages import constants as message_constants

# Load environment FIRST
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep secret key in env in production
SECRET_KEY = os.get_env("SECRET_KEY")

DEBUG = os.getenv("DEBUG", "False").lower() == "true"

ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "").split(",") if os.getenv("ALLOWED_HOSTS") else []

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',

    'core.apps.CoreConfig',
    'user.apps.UserConfig',
    'finance.apps.FinanceConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'mmf.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'mmf.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Africa/Nairobi'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [os.path.join(BASE_DIR, "static")]

LOGIN_URL = '/user/login/'
LOGIN_REDIRECT_URL = 'user:profile'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ======================
# ENV VARIABLES (MPESA)
# ======================

import os
from django.core.exceptions import ImproperlyConfigured

def get_env(var_name):
    value = os.getenv(var_name)
    if not value:
        raise ImproperlyConfigured(f"Missing environment variable: {var_name}")
    return value


CONSUMER_KEY = get_env("CONSUMER_KEY")
CONSUMER_SECRET = get_env("CONSUMER_SECRET")

MPESA_PASSKEY = get_env("MPESA_PASSKEY")
MPESA_SHORTCODE = get_env("MPESA_SHORTCODE")
MPESA_BASE_URL = get_env("MPESA_BASE_URL")

STK_CALLBACK_URL = get_env("STK_CALLBACK_URL")

PUBLIC_URL = get_env("PUBLIC_URL")

AUTH_USER_MODEL = "user.CustomUser"
STATIC_ROOT = BASE_DIR / "staticfiles"
# ======================
# EMAIL (FIXED SECURITY)
# ======================
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True

EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD")

# ======================
# MESSAGES FIX
# ======================
MESSAGE_STORAGE = 'django.contrib.messages.storage.session.SessionStorage'

MESSAGE_TAGS = {
    message_constants.ERROR: 'error',
    message_constants.SUCCESS: 'success',
    message_constants.INFO: 'info',
    message_constants.WARNING: 'warning',
}