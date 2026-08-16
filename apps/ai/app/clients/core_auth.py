"""Django 서비스 계정 인증 — ai가 core에 **쓰기**를 할 때 쓰는 공용 통로.

ai는 사람 세션이 없다. 그런데 룰 그래프 DRAFT 저장·적재 결과 회신처럼 쓰기가 필요한
경로가 생겼고, 그 엔드포인트들은 capability(`rule_view`)를 요구한다. 그래서 최소 권한
서비스 계정(`rule-agent`)으로 JWT를 받아 붙인다.

**정적 토큰을 env에 박는 방식은 못 쓴다** — SimpleJWT access 수명이 짧다(기본 5분).
여기서 직접 발급하고, 만료로 401이 오면 한 번 재발급해 재시도한다. 재시도를 1회로 묶는
이유는 자격증명이 틀린 경우와 만료를 구분하지 못한 채 반복하면 로그인 실패를 무한
재시도하기 때문이다.

계정 준비: `docker compose exec core python manage.py ensure_service_account`
"""
from __future__ import annotations

import os
import threading

import httpx

from app.config import settings as core_settings

TIMEOUT = 20.0

SERVICE_USER = os.environ.get("RULE_AGENT_SERVICE_USER", "rule-agent")
SERVICE_PASSWORD = os.environ.get("RULE_AGENT_SERVICE_PASSWORD", "")


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
            f"RULE_AGENT_SERVICE_PASSWORD 가 비어 있다 — 서비스 계정({SERVICE_USER})으로 "
            "로그인할 수 없어 core 쓰기 API가 403을 낸다. 레포 루트 `.env`에 값을 넣고 "
            "`manage.py ensure_service_account`로 계정을 만들 것"
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
        raise ServiceAuthError(
            f"서비스 계정 인증 실패({resp.status_code}) — 계정 `{SERVICE_USER}`가 있는지, "
            f"비밀번호가 맞는지 확인할 것. 응답: {resp.text[:200]}"
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
            "없다. `manage.py ensure_service_account`로 부여할 것"
        )
    resp.raise_for_status()
    return resp
