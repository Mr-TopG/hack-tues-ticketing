from datetime import timedelta
from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, []),
    DJANGO_CSRF_TRUSTED_ORIGINS=(list, []),
)

env_file = PROJECT_ROOT / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)


SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)

ALLOWED_HOSTS = env.list(
    "DJANGO_ALLOWED_HOSTS",
    default=["localhost", "127.0.0.1"],
)

CSRF_TRUSTED_ORIGINS = env.list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    default=[],
)


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "apps.events.apps.EventsConfig",
    "apps.tickets.apps.TicketsConfig",
]


MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "allauth.account.middleware.AccountMiddleware",
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
    "default": env.db("DATABASE_URL"),
}


AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "MinimumLengthValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "CommonPasswordValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "NumericPasswordValidator"
        ),
    },
]


LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Sofia"

USE_I18N = True
USE_TZ = True


STATIC_URL = env("STATIC_URL", default="/static/")
STATIC_ROOT = Path(
    env("STATIC_ROOT", default="/app/staticfiles")
)
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = env("MEDIA_URL", default="/media/")
MEDIA_ROOT = Path(
    env("MEDIA_ROOT", default="/app/media")
)
PRIVATE_MEDIA_ROOT = Path(
    env(
        "PRIVATE_MEDIA_ROOT",
        default="/app/private-media",
    )
)

STORAGES = {
    "default": {
        "BACKEND": (
            "django.core.files.storage.FileSystemStorage"
        ),
    },
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
        ),
    },
    "ticket_pdfs": {
        "BACKEND": (
            "apps.tickets.storage.PrivateFileSystemStorage"
        ),
        "OPTIONS": {
            "location": PRIVATE_MEDIA_ROOT,
            "file_permissions_mode": 0o600,
            "directory_permissions_mode": 0o700,
        },
    },
}


EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)

DEFAULT_FROM_EMAIL = env(
    "DEFAULT_FROM_EMAIL",
    default="Hack TUES Tickets <tickets@example.com>",
)
SERVER_EMAIL = env(
    "SERVER_EMAIL",
    default="server@example.com",
)
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=False)
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=10)

if EMAIL_USE_TLS and EMAIL_USE_SSL:
    raise ImproperlyConfigured(
        "EMAIL_USE_TLS and EMAIL_USE_SSL cannot both be enabled."
    )

if EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend":
    if not EMAIL_HOST:
        raise ImproperlyConfigured(
            "EMAIL_HOST is required when the SMTP email backend is enabled."
        )

    if bool(EMAIL_HOST_USER) != bool(EMAIL_HOST_PASSWORD):
        raise ImproperlyConfigured(
            "EMAIL_HOST_USER and EMAIL_HOST_PASSWORD must be configured "
            "together."
        )


CELERY_BROKER_URL = env(
    "CELERY_BROKER_URL",
    default="redis://redis:6379/1",
)
CELERY_RESULT_BACKEND = env(
    "CELERY_RESULT_BACKEND",
    default="redis://redis:6379/2",
)
CELERY_TASK_ALWAYS_EAGER = env.bool(
    "CELERY_TASK_ALWAYS_EAGER",
    default=False,
)
CELERY_TASK_EAGER_PROPAGATES = env.bool(
    "CELERY_TASK_EAGER_PROPAGATES",
    default=False,
)
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ("json",)
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "dispatch-pending-ticket-emails": {
        "task": (
            "apps.tickets.tasks."
            "dispatch_pending_ticket_emails"
        ),
        "schedule": 60.0,
    },
}


SESSION_COOKIE_SECURE = env.bool(
    "SESSION_COOKIE_SECURE",
    default=False,
)

CSRF_COOKIE_SECURE = env.bool(
    "CSRF_COOKIE_SECURE",
    default=False,
)

SECURE_SSL_REDIRECT = env.bool(
    "SECURE_SSL_REDIRECT",
    default=False,
)

SECURE_HSTS_SECONDS = env.int(
    "SECURE_HSTS_SECONDS",
    default=0,
)

SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS",
    default=False,
)

SECURE_HSTS_PRELOAD = env.bool(
    "SECURE_HSTS_PRELOAD",
    default=False,
)

if env.bool(
    "SECURE_PROXY_SSL_HEADER_ENABLED",
    default=False,
):
    SECURE_PROXY_SSL_HEADER = (
        "HTTP_X_FORWARDED_PROTO",
        "https",
    )


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


AUTH_USER_MODEL = "accounts.User"

APP_BASE_URL = env(
    "APP_BASE_URL",
    default="http://localhost:8000",
).rstrip("/")

TICKET_PDF_FONT_PATH = env(
    "TICKET_PDF_FONT_PATH",
    default=(
        "/usr/share/fonts/truetype/dejavu/"
        "DejaVuSans.ttf"
    ),
)

TICKET_PDF_BOLD_FONT_PATH = env(
    "TICKET_PDF_BOLD_FONT_PATH",
    default=(
        "/usr/share/fonts/truetype/dejavu/"
        "DejaVuSans-Bold.ttf"
    ),
)

MAX_TICKET_FILE_SIZE = env.int(
    "MAX_TICKET_FILE_SIZE",
    default=5_242_880,
)
EMAIL_DELIVERY_MAX_RETRIES = env.int(
    "EMAIL_DELIVERY_MAX_RETRIES",
    default=5,
)
TICKET_EMAIL_RESEND_COOLDOWN = timedelta(
    seconds=env.int(
        "TICKET_EMAIL_RESEND_COOLDOWN_SECONDS",
        default=60,
    )
)
TICKET_EMAIL_STALE_AFTER = timedelta(
    seconds=env.int(
        "TICKET_EMAIL_STALE_AFTER_SECONDS",
        default=900,
    )
)

EMAIL_VERIFICATION_MAX_AGE = env.int(
    "EMAIL_VERIFICATION_MAX_AGE",
    default=86400,
)

LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "home"

# django-allauth

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_USER_MODEL_EMAIL_FIELD = "email"

ACCOUNT_LOGIN_METHODS = {"email"}

ACCOUNT_SIGNUP_FIELDS = [
    "email*",
    "password1*",
    "password2*",
]

ACCOUNT_SIGNUP_FORM_CLASS = (
    "apps.accounts.forms.AdditionalSignupForm"
)

ACCOUNT_EMAIL_VERIFICATION = "mandatory"

ACCOUNT_EMAIL_CONFIRMATION_EXPIRE_DAYS = env.int(
    "ACCOUNT_EMAIL_CONFIRMATION_EXPIRE_DAYS",
    default=1,
)

ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_LOGOUT_REDIRECT_URL = "home"
ACCOUNT_EMAIL_SUBJECT_PREFIX = "[Hack TUES Tickets] "

ACCOUNT_PREVENT_ENUMERATION = True
ACCOUNT_SIGNUP_FORM_HONEYPOT_FIELD = "phone_number"

SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
SOCIALACCOUNT_LOGIN_ON_GET = False
SOCIALACCOUNT_STORE_TOKENS = False

_google_oauth_client_id = env(
    "GOOGLE_OAUTH_CLIENT_ID",
    default="",
).strip()
_google_oauth_client_secret = env(
    "GOOGLE_OAUTH_CLIENT_SECRET",
    default="",
).strip()

if bool(_google_oauth_client_id) != bool(
    _google_oauth_client_secret
):
    raise ImproperlyConfigured(
        "GOOGLE_OAUTH_CLIENT_ID and "
        "GOOGLE_OAUTH_CLIENT_SECRET must be configured together."
    )

_google_provider = {
    "SCOPE": [
        "profile",
        "email",
    ],
    "AUTH_PARAMS": {
        "access_type": "online",
    },
    "OAUTH_PKCE_ENABLED": True,
    "EMAIL_AUTHENTICATION": True,
}

if _google_oauth_client_id:
    _google_provider["APP"] = {
        "client_id": _google_oauth_client_id,
        "secret": _google_oauth_client_secret,
        "key": "",
    }

SOCIALACCOUNT_PROVIDERS = {
    "google": _google_provider,
}
