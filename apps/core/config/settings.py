"""Django 설정 (Core Backend = System of Record).

기술명세서 §1.3 기준: 인증·RBAC, 도메인 CRUD, 정산 상태머신, ERP 전표(안),
Postgres 소유. LLM/ML 직접 호출은 하지 않고 FastAPI(ai)에 위임한다.
"""
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DJANGO_DEBUG=(bool, True))

environ.Env.read_env(BASE_DIR / ".env")   # ← 이 줄 추가

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
    "domain.notifications",  # 알림(메시지 + 이동할 페이지)
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

# 커스텀 유저(역할·팀 포함). 그린필드이므로 최초 마이그레이션 전에 지정.
AUTH_USER_MODEL = "accounts.User"

# ── DRF / JWT ───────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        # 세션 인증(SPA, dev CSRF 생략) — JWT는 보류(추후 병행 가능)
        "domain.common.authentication.CsrfExemptSessionAuthentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    # 스캐폴드 단계: 우선 열어둠. 실제 RBAC는 역할별 권한으로 교체 예정.
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.AllowAny",),
    # 금액(Decimal)을 문자열이 아닌 숫자로 직렬화 → 프론트 정수 처리 편의.
    "COERCE_DECIMAL_TO_STRING": False,
}

# 개발용 CORS (web:5173에서 직접 호출 시). Nginx 경유 시엔 same-origin.
CORS_ALLOW_ALL_ORIGINS = DEBUG

# ── 내부 서비스 ─────────────────────────────────────────────────
AI_BASE_URL = env("AI_BASE_URL", default="http://ai:9000")  # FastAPI(AI) 위임 대상

# ── 로깅 ────────────────────────────────────────────────────────
# `LOG_DIR`이 설정되면 파일에도 남긴다(compose가 `/logs`를 호스트 `./logs`에 바인드).
# **비어 있으면 콘솔만** — 로컬 `manage.py test`가 컨테이너 경로(`/logs`)를 못 만들어
# 죽는 것을 막는다. 즉 파일 로깅은 docker 실행에서만 켜진다.
LOG_DIR = env("LOG_DIR", default="")
LOG_LEVEL = env("LOG_LEVEL", default="INFO")

_handlers = ["console"]
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        # 컨테이너 2개가 각자 파일에 쓰므로 어느 쪽 로그인지 파일명으로 갈린다.
        # 여기서는 "언제·어디서·무엇"만 고정한다.
        "standard": {
            "format": "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
    },
    "root": {"handlers": _handlers, "level": LOG_LEVEL},
    "loggers": {
        # 요청 실패(4xx/5xx)를 파일에서 보려면 이 로거가 필요하다. propagate로 root에 얹는다.
        "django.request": {"level": "WARNING", "propagate": True},
        "django.server": {"level": "INFO", "propagate": True},
        "domain": {"level": LOG_LEVEL, "propagate": True},
    },
}

if LOG_DIR:
    from pathlib import Path as _Path

    _Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
    LOGGING["handlers"]["file"] = {
        # 무한히 커지면 볼륨을 채운다 — 5MB × 3개로 묶는다.
        "class": "logging.handlers.RotatingFileHandler",
        "filename": str(_Path(LOG_DIR) / "core.log"),
        "maxBytes": 5 * 1024 * 1024,
        "backupCount": 3,
        "encoding": "utf-8",
        "formatter": "standard",
    }
    _handlers.append("file")
