"""Django 설정 (Core Backend = System of Record).

기술명세서 §1.3 기준: 인증·RBAC, 도메인 CRUD, 정산 상태머신, ERP 전표(안),
Postgres 소유. LLM/ML 직접 호출은 하지 않고 FastAPI(ai)에 위임한다.
"""
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DJANGO_DEBUG=(bool, True))

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-secret-key-change-me")
DEBUG = env("DJANGO_DEBUG", default=True)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["*"])

# ── Applications ────────────────────────────────────────────────
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # 3rd-party
    "rest_framework",
    "corsheaders",
    # domain (기술명세서 §3.1 테이블 매핑)
    "domain.common",
    "domain.accounts",     # users / teams / roles (RBAC)
    "domain.cards",        # cards
    "domain.transactions", # transactions / receipts
    "domain.settlements",  # settlements / settlement_events (상태머신)
    "domain.policies",     # policies / rules / rule_hits
    "domain.risk",         # risk_reviews / decision_labels
    "domain.erp",          # erp_vouchers
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

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ── Database : Postgres(SoT) ────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", default="settlement"),
        "USER": env("POSTGRES_USER", default="settlement"),
        "PASSWORD": env("POSTGRES_PASSWORD", default="settlement"),
        "HOST": env("POSTGRES_HOST", default="db"),
        "PORT": env("POSTGRES_PORT", default="5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = []  # MVP 스캐폴드: 개발 편의로 완화

LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"  # 증빙 이미지(로컬 볼륨). 운영은 Object Storage.

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── DRF / JWT ───────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    # 스캐폴드 단계: 우선 열어둠. 실제 RBAC는 역할별 권한으로 교체 예정.
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.AllowAny",),
}

# 개발용 CORS (web:5173에서 직접 호출 시). Nginx 경유 시엔 same-origin.
CORS_ALLOW_ALL_ORIGINS = DEBUG

# ── 내부 서비스 ─────────────────────────────────────────────────
AI_BASE_URL = env("AI_BASE_URL", default="http://ai:9000")  # FastAPI(AI) 위임 대상
