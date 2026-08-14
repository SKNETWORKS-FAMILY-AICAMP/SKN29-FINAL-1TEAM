# apps/ai/app/agents/rule_agent_v0/django_client.py
"""Django 내부 API 클라이언트 — Rule Agent 생성 flow.

그래프 저장용 전용 API는 만들지 않는다. 룰 콘솔이 이미 쓰는 증분식 API를 그대로
오케스트레이션하면 같은 결과가 나오고, 감사로그·불변식(`services.py`)도 함께 탄다:

    POST  /api/rules/drafts/                     빈 그래프(v1, DRAFT, scope) 생성
    POST  /api/rules/{id}/nodes/                  빈 노드 생성 (최초 생성 노드가 자동 entry)
    PATCH /api/rules/{id}/nodes/{node_key}/       condition/conditionText/action/routings 채움

인증: 위 3개는 `CanViewRule`(capability `rule_view`)을 요구한다 — 사람이 룰 콘솔에
로그인해 쓰는 걸 전제로 만든 권한이다. Rule Agent는 세션이 없으므로 **전용 서비스
계정으로 JWT를 받아** Bearer로 붙인다. access 토큰 수명이 짧아(SimpleJWT 기본 5분)
정적 토큰을 env에 박아두는 방식은 못 쓴다 — 그래서 여기서 직접 발급하고, 만료로
401이 오면 한 번 재발급해 재시도한다.

계정 준비: `docker compose exec core python manage.py ensure_service_account`
"""
from __future__ import annotations

import threading
from typing import Any

import httpx

from app.config import settings as core_settings

from .settings import settings

_TIMEOUT = 20.0


def _base() -> str:
    """Django 주소는 중앙 설정(compose `CORE_BASE_URL`)을 쓴다 — 사본을 두지 않는다."""
    return core_settings.core_base_url.rstrip("/")


class ServiceAuthError(RuntimeError):
    """서비스 계정 인증 실패 — 익명으로 조용히 진행하지 않고 여기서 멈춘다."""


# ---------------------------------------------------------------- JWT 토큰 관리

_lock = threading.Lock()
_access_token: str | None = None


def _mint_token() -> str:
    """서비스 계정으로 access 토큰 발급. 실패 사유를 삼키지 않는다."""
    if not settings.service_password:
        raise ServiceAuthError(
            f"RULE_AGENT_SERVICE_PASSWORD 가 비어 있다 — 서비스 계정({settings.service_user})으로 "
            "로그인할 수 없어 룰 콘솔 API가 403을 낸다. 레포 루트 `.env`에 값을 넣고 "
            "`manage.py ensure_service_account`로 계정을 만들 것"
        )
    try:
        r = httpx.post(
            f"{_base()}/api/auth/token/",
            json={"username": settings.service_user, "password": settings.service_password},
            timeout=_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        raise ServiceAuthError(f"Django({_base()}) 연결 실패: {type(exc).__name__}: {exc}") from exc
    if r.status_code != 200:
        raise ServiceAuthError(
            f"서비스 계정 인증 실패({r.status_code}) — 계정 `{settings.service_user}`가 있는지, "
            f"비밀번호가 맞는지 확인할 것. 응답: {r.text[:200]}"
        )
    token = r.json().get("access")
    if not token:
        raise ServiceAuthError(f"토큰 응답에 access 없음: {r.text[:200]}")
    return token


def _token(refresh: bool = False) -> str:
    global _access_token
    with _lock:
        if refresh or _access_token is None:
            _access_token = _mint_token()
        return _access_token


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    """인증 붙여 호출하고, 만료(401)면 **한 번만** 재발급해 재시도한다.

    재시도를 1회로 묶는 이유: 자격증명이 틀린 경우와 토큰이 만료된 경우를 구분 못 한 채
    반복하면 로그인 실패를 무한 재시도하게 된다.
    """
    url = f"{_base()}{path}"
    resp = httpx.request(
        method, url, headers={"Authorization": f"Bearer {_token()}"}, timeout=_TIMEOUT, **kwargs
    )
    if resp.status_code == 401:
        resp = httpx.request(
            method, url,
            headers={"Authorization": f"Bearer {_token(refresh=True)}"},
            timeout=_TIMEOUT, **kwargs,
        )
    if resp.status_code == 403:
        raise ServiceAuthError(
            f"권한 부족(403) {path} — 서비스 계정 `{settings.service_user}`에 capability "
            "`rule_view`가 없다. `manage.py ensure_service_account`로 부여할 것"
        )
    resp.raise_for_status()
    return resp


# ---------------------------------------------------------------- 조회

def get_eval_context_schema() -> list[str]:
    """EvalContext 허용 경로 카탈로그. SoT는 Django `eval_context.py`.

    `EvalContextSchemaView`(AllowAny)라 인증과 무관하게 동작해야 한다. 조회에 실패하면
    빈 목록을 돌려주고, 프롬프트가 "허용 경로 조회 실패" 안내로 대체한다 — 여기서
    멈추면 스키마 조회 장애가 생성 전체를 막는다.
    """
    try:
        r = httpx.get(f"{_base()}/api/internal/rule-agent-v0/eval-context-schema/", timeout=_TIMEOUT)
        r.raise_for_status()
        return list(r.json().get("paths", []))
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------- 쓰기

def create_rule_graph_draft(
    name: str,
    scope: str,
    nodes: list[dict[str, Any]],
    routings_by_node: dict[str, list[dict[str, str]]],
    generation_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """룰 콘솔 API 3종을 순서대로 호출해 그래프+노드+라우팅을 만든다.

    nodes: `_assemble_linear_graph()`가 만든 노드 리스트. **리스트 순서 = 생성 순서 =
           entry 결정 순서**다(첫 호출로 생성되는 노드가 자동으로 `entry_node_key`가
           된다 — `RuleGraphViewSet.create_node` 참조).
    routings_by_node: {node_key: [{"onResult": "MATCH"|"NO_MATCH", "toNodeKey": "..."}]}
                      camelCase — `update_node`가 `request.data`를 그대로 읽으므로
                      프론트와 같은 표기여야 한다.

    scope 문자열은 Django `normalize_scope`가 Category 값으로 접는다(규정 표기 허용).
    항상 새 계열(v1)만 만든다 — 기존 계열에 버전 추가(`POST /api/rules/{id}/versions`)는
    아직 미지원.
    """
    graph = _request(
        "POST", "/api/rules/drafts/",
        json={"name": name, "scope": scope, "generationMeta": generation_meta or {}},
    ).json()
    graph_id = graph.get("id")

    created_nodes: list[str] = []
    for node in nodes:
        node_key = node["node_key"]
        _request("POST", f"/api/rules/{graph_id}/nodes/", json={"nodeKey": node_key})
        created_nodes.append(node_key)
        _request(
            "PATCH", f"/api/rules/{graph_id}/nodes/{node_key}/",
            json={
                "condition": node["condition"],
                "conditionText": node["condition_text"],
                "action": node["action"],
                "routings": routings_by_node.get(node_key, []),
            },
        )

    return {
        "graph_id": graph_id,
        "family_key": graph.get("familyKey") or graph.get("family_key"),
        "version": graph.get("version"),
        "scope": graph.get("scope"),
        "status": graph.get("status"),
        "created_nodes": created_nodes,
    }
