# apps/ai/app/agents/rule_agent_v0/django_client.py
"""Django 내부 API 클라이언트 — Rule Agent 생성 flow.

그래프 저장용 전용 API는 만들지 않는다. 룰 콘솔이 이미 쓰는 증분식 API를 그대로
오케스트레이션하면 같은 결과가 나오고, 감사로그·불변식(`services.py`)도 함께 탄다:

    POST  /api/rules/drafts/                     빈 그래프(v1, DRAFT, scope) 생성
    POST  /api/rules/{id}/nodes/                  빈 노드 생성 (최초 생성 노드가 자동 entry)
    PATCH /api/rules/{id}/nodes/{node_key}/       condition/conditionText/action/routings 채움

인증: 위 3개는 `CanViewRule`(capability `rule_view`)을 요구한다 — 사람이 룰 콘솔에
로그인해 쓰는 걸 전제로 만든 권한이다. Rule Agent는 세션이 없으므로 전용 서비스 계정으로
JWT를 받아 붙인다. 그 발급·갱신 로직은 `app/clients/core_auth.py`가 갖고 있다(적재 결과
회신 등 다른 쓰기 경로와 공유).

계정 준비: `docker compose exec core python manage.py ensure_service_account`
"""
from __future__ import annotations

from typing import Any

import httpx

from app.clients import core_auth
from app.clients.core_auth import ServiceAuthError  # noqa: F401  — 기존 호출부 호환

_TIMEOUT = core_auth.TIMEOUT
_base = core_auth.base
_request = core_auth.request


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


def get_action_schema() -> dict[str, Any]:
    """decision/severity 선택지 카탈로그. SoT는 Django `engine.py`(§8 후속, 2026-08-19).

    이전엔 이 파일을 호출하는 `agent.py`가 `DECISIONS`/`SEVERITIES`를 직접 하드코딩했다
    (프론트 `DraftTab.tsx`도 별도로 하드코딩 — 3곳에 독립 존재). 조회 실패 시엔 그 옛
    하드코딩 값을 기본값으로 돌려준다 — Django가 잠깐 안 떠 있어도 룰 생성 자체가
    막히면 안 된다(§ `get_eval_context_schema`와 같은 원칙).
    """
    fallback = {"decisions": ["PASS", "REJECT", "RETURN", "REVIEW", "PASS_THROUGH"],
                "severities": ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"], "passThrough": "PASS_THROUGH"}
    try:
        r = httpx.get(f"{_base()}/api/internal/rule-agent-v0/action-schema/", timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if data.get("decisions") and data.get("severities"):
            return data
        return fallback
    except Exception:  # noqa: BLE001
        return fallback


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


def simulate_graph(graph_id: str, narrate: bool = True) -> dict[str, Any]:
    """검증 시뮬레이션 실행 — 구조검증(`validate_graph`) + 검증셋/직전달 내역 판정.

    `simulate()`(Django, 저장 없음)를 감싸는 `POST /api/rules/{id}/simulate` 액션이
    실행 결과를 `RuleSimulationRun`으로 **저장**한다(호출할 때마다 실행 이력에 남음).
    응답의 `structureError`가 빈 문자열이면 구조적으로 유효한 그래프.

    `narrate=False`면 Django가 서술(LLM narrate-report) 생성을 건너뛴다 — 아무도 읽지 않는
    내부 검증 호출(`testcases.py` 자체검증 루프)에서 심층 모델 호출을 아끼기 위함.

    `narrate=True`일 때는 기본 20초(`core_auth.TIMEOUT`)보다 넉넉하게 잡는다 — Django가
    내부적으로 narrate-report(심층 모델, 최대 60초 예산)를 기다리므로, 이 호출의 타임아웃이
    그보다 짧으면 Django 응답이 오기도 전에 여기서 먼저 끊어진다(2026-08-18 실사용 발견 —
    검증셋 자동생성의 마지막 호출이 20초 만에 ReadTimeout으로 끊겼었다).
    """
    timeout = 75.0 if narrate else None
    kwargs = {"timeout": timeout} if timeout else {}
    return _request("POST", f"/api/rules/{graph_id}/simulate/", json={"narrate": narrate}, **kwargs).json()


def get_latest_simulation(graph_id: str) -> dict[str, Any] | None:
    """최신 시뮬레이션 보고서. 실행 이력이 없으면 None(204) — 대화형 수정(§4)이 "이 노드가
    위험건을 만들고 있다" 같은 사실을 프롬프트에 얹을 때 쓴다. 없으면 그냥 그 맥락 없이 진행."""
    resp = _request("GET", f"/api/rules/{graph_id}/simulation/")
    if resp.status_code == 204:
        return None
    return resp.json()


def discard_draft(graph_id: str) -> None:
    """DRAFT 그래프 폐기. 검증 실패로 재생성해야 할 때 이전 시도의 그래프를 지운다."""
    _request("DELETE", f"/api/rules/{graph_id}/draft/")


# ------------------------------------------------------- 대화형 수정(§1.2-5)용

def get_graph(graph_id: str) -> dict[str, Any]:
    """그래프 현재 상태(노드·라우팅·entry) 조회. `RuleGraphSerializer` 그대로."""
    return _request("GET", f"/api/rules/{graph_id}/").json()


def create_node(graph_id: str, node_key: str) -> dict[str, Any]:
    """빈 노드 생성. 바로 뒤에 `update_node`로 내용을 채워야 한다(콘솔과 같은 2단계)."""
    return _request("POST", f"/api/rules/{graph_id}/nodes/", json={"nodeKey": node_key}).json()


def update_node(
    graph_id: str,
    node_key: str,
    *,
    condition: Any = None,
    condition_text: str | None = None,
    action: dict[str, Any] | None = None,
    routings: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """노드 내용 갱신 — 넘긴 필드만 반영(camelCase, `update_node` 액션이 request.data를
    그대로 읽으므로 프론트와 같은 표기)."""
    payload: dict[str, Any] = {}
    if condition is not None:
        payload["condition"] = condition
    if condition_text is not None:
        payload["conditionText"] = condition_text
    if action is not None:
        payload["action"] = action
    if routings is not None:
        payload["routings"] = routings
    return _request("PATCH", f"/api/rules/{graph_id}/nodes/{node_key}/", json=payload).json()


def delete_node(graph_id: str, node_key: str) -> None:
    """노드 삭제. 참조하던 라우팅도 Django 쪽에서 같이 정리된다(`update_node` DELETE 분기)."""
    _request("DELETE", f"/api/rules/{graph_id}/nodes/{node_key}/")


def get_messages(graph_id: str) -> list[dict[str, Any]]:
    """대화 로그 조회 — 기존 `RuleAuthoringMessage` 저장소. `[{"role","text","appliedNote",...}]`."""
    return _request("GET", f"/api/rules/{graph_id}/messages/").json()


def post_messages(
    graph_id: str, entries: list[dict[str, Any]], node_key: str = ""
) -> dict[str, Any]:
    """대화 로그 적재 — 기존 `RuleAuthoringMessage` 저장소 재사용(신규 저장 경로 아님).

    entries: [{"role": "user"|"ai", "text": ..., "appliedNote": ...}]
    """
    return _request(
        "POST", f"/api/rules/{graph_id}/messages/",
        json={"nodeKey": node_key, "messages": entries},
    ).json()


# ------------------------------------------------------- 검증셋 자동생성용

def get_test_cases(graph_id: str) -> list[dict[str, Any]]:
    """저장된 검증셋 조회. `RuleTestCase` 그대로(camelCase)."""
    return _request("GET", f"/api/rules/{graph_id}/test-cases/").json()


def put_test_cases(graph_id: str, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """검증셋 통째로 교체. append로 쓰려면 호출 전에 기존 것과 합쳐서 넘겨야 한다
    (`replace_test_cases`가 전체 교체라 Django API 자체엔 append가 없음)."""
    return _request("PUT", f"/api/rules/{graph_id}/test-cases/", json={"testCases": cases}).json()
