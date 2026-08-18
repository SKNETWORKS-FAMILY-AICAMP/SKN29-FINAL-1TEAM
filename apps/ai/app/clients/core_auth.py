"""Django 서비스 계정 인증 — ai가 core에 **쓰기**를 할 때 쓰는 공용 통로.

ai는 사람 세션이 없다. 그런데 룰 그래프 DRAFT 저장·적재 결과 회신처럼 쓰기가 필요한
경로가 생겼고, 그 엔드포인트들은 capability(`rule_view`)를 요구한다. 그래서 최소 권한
서비스 계정으로 JWT를 받아 붙인다.

**Agent마다 계정을 나누지 않는다 — 하나다.** 쓰기 경로들이 요구하는 권한이 같고,
계정을 늘리면 비밀번호를 늘린 만큼 어긋날 자리가 늘어난다.

**정적 토큰을 env에 박는 방식은 못 쓴다** — SimpleJWT access 수명이 짧다(기본 5분).
여기서 직접 발급하고, 만료로 401이 오면 한 번 재발급해 재시도한다. 재시도를 1회로 묶는
이유는 자격증명이 틀린 경우와 만료를 구분하지 못한 채 반복하면 로그인 실패를 무한
재시도하기 때문이다.

계정 준비: `docker compose exec core python manage.py ensure_service_account`
진단(401이 날 때): `... ensure_service_account --check`
"""
from __future__ import annotations

import os
import threading

import httpx

from app.config import settings as core_settings

TIMEOUT = 20.0

# 새 이름 우선, 구 이름 폴백. 이름이 `RULE_AGENT_*`라 "Agent마다 계정이 따로인가?"라는
# 오해를 만들었다 — core의 `ensure_service_account`도 같은 순서로 읽는다(양쪽이 같아야 한다).
SERVICE_USER = (
    os.environ.get("AI_SERVICE_USER")
    or os.environ.get("RULE_AGENT_SERVICE_USER")
    or "rule-agent"
)
SERVICE_PASSWORD = (
    os.environ.get("AI_SERVICE_PASSWORD", "").strip()
    or os.environ.get("RULE_AGENT_SERVICE_PASSWORD", "").strip()
)


class ServiceAuthError(RuntimeError):
    """서비스 계정 인증 실패 — 익명으로 조용히 진행하지 않고 여기서 멈춘다."""


def base() -> str:
    """core 주소는 중앙 설정(compose `CORE_BASE_URL`)만 본다 — 사본을 두지 않는다."""
    return core_settings.core_base_url.rstrip("/")


_lock = threading.Lock()
_access_token: str | None = None


def _mint() -> str:
    if not SERVICE_PASSWORD:
        raise ServiceAuthError(
            f"AI_SERVICE_PASSWORD 가 비어 있다 — 서비스 계정({SERVICE_USER})으로 로그인할 수 없다. "
            "레포 루트 `.env`에 값을 넣고 컨테이너를 재생성한 뒤 "
            "`manage.py ensure_service_account`를 실행할 것"
        )
    try:
        resp = httpx.post(
            f"{base()}/api/auth/token/",
            json={"username": SERVICE_USER, "password": SERVICE_PASSWORD},
            timeout=TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        raise ServiceAuthError(f"Django({base()}) 연결 실패: {type(exc).__name__}: {exc}") from exc
    if resp.status_code != 200:
        # 401 "No active account found"는 셋 중 하나다: 계정 없음 / 비밀번호 불일치 /
        # 비활성. 어느 쪽인지는 core에서만 알 수 있으므로 진단 명령을 직접 가리킨다.
        raise ServiceAuthError(
            f"서비스 계정 인증 실패({resp.status_code}) — 계정 `{SERVICE_USER}` @ {base()}.\n"
            f"  응답: {resp.text[:200]}\n"
            "  진단: docker compose exec core python manage.py ensure_service_account --check\n"
            "  대개는 core 쪽 계정이 비밀번호 없이 만들어졌거나 env가 서로 다른 경우다 "
            "(env를 바꿨다면 `docker compose up -d --force-recreate core ai`가 필요하다)."
        )
    token = resp.json().get("access")
    if not token:
        raise ServiceAuthError(f"토큰 응답에 access 없음: {resp.text[:200]}")
    return token


def token(refresh: bool = False) -> str:
    global _access_token
    with _lock:
        if refresh or _access_token is None:
            _access_token = _mint()
        return _access_token


def _is_expired_token(resp: httpx.Response) -> bool:
    """이 배포의 SimpleJWT는 만료된 토큰도 401이 아니라 **403**으로 응답한다
    (`{"code": "token_not_valid", ...}`). 진짜 capability 부족(403, 다른 detail —
    예: "룰 콘솔 권한이 필요합니다.")과 구분해야 한다 — 구분 없이 모든 403을 재시도하면
    진짜 권한 문제까지 뭉뚱그려 재시도하게 되고, 반대로 구분 없이 401만 재시도하면
    (기존 동작) 만료된 토큰이 영원히 재발급되지 않아 서버가 재시작 전까지 계속
    403만 내는 상태로 고착된다(실측: 2026-08-16, 5분 TTL 만료 후 재현).
    """
    try:
        return resp.json().get("code") == "token_not_valid"
    except ValueError:
        return False


def request(method: str, path: str, **kwargs) -> httpx.Response:
    """인증을 붙여 core를 호출한다. 만료(401, 또는 이 배포에서 실제로 관측되는
    403 token_not_valid)면 한 번만 재발급해 재시도."""
    url = f"{base()}{path}"
    timeout = kwargs.pop("timeout", TIMEOUT)
    resp = httpx.request(
        method, url, headers={"Authorization": f"Bearer {token()}"}, timeout=timeout, **kwargs
    )
    if resp.status_code == 401 or (resp.status_code == 403 and _is_expired_token(resp)):
        resp = httpx.request(
            method, url, headers={"Authorization": f"Bearer {token(refresh=True)}"},
            timeout=timeout, **kwargs,
        )
    if resp.status_code == 403:
        raise ServiceAuthError(
            f"권한 부족(403) {path} — 서비스 계정 `{SERVICE_USER}`에 capability `rule_view`가 "
            "없다. `manage.py ensure_service_account`로 부여할 것 "
            "(진단: `... ensure_service_account --check`)"
        )
    resp.raise_for_status()
    return resp
