import os
from pathlib import Path
from dotenv import load_dotenv

from django.contrib.messages import constants as message_constants

# Load environment FIRST
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep secret key in env in production
SECRET_KEY = os.getenv("SECRET_KEY", "django-insecure-fallback-key")

DEBUG = os.getenv("DEBUG", "True") == "True"

ALLOWED_HOSTS = [
    '127.0.0.1',
    'localhost',
    'ghostlier-cloudily-coleman.ngrok-free.dev',
]

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
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
MPESA_PASSKEY = os.getenv("MPESA_PASSKEY")
MPESA_SHORTCODE = os.getenv("MPESA_SHORTCODE")
MPESA_BASE_URL = os.getenv("MPESA_BASE_URL")

MPESA_B2C_INITIATOR = os.getenv("MPESA_B2C_INITIATOR")
MPESA_B2C_SECURITY_CREDENTIAL = os.getenv("MPESA_B2C_SECURITY_CREDENTIAL")
MPESA_B2C_PARTYA = os.getenv("MPESA_B2C_PARTYA")

PUBLIC_URL = os.getenv("PUBLIC_URL")

CALLBACK_URL = f"{PUBLIC_URL}/finance/callback/"
STK_CALLBACK_URL = os.getenv("STK_CALLBACK_URL")
B2C_RESULT_URL = os.getenv("B2C_RESULT_URL")
B2C_TIMEOUT_URL = os.getenv("B2C_TIMEOUT_URL")

AUTH_USER_MODEL = 'user.CustomUser'

CSRF_TRUSTED_ORIGINS = [
    "https://ghostlier-cloudily-coleman.ngrok-free.dev"
]

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