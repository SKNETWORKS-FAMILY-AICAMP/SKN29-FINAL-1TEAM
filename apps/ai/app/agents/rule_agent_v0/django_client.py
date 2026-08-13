# apps/ai/app/agents/rule_agent_v0/django_client.py
"""Django 내부 API 클라이언트 — v0.

설계 변경(2026-08-13, 실물 `domain/policies/views.py` 확인 후): 애초 계획했던
"그래프+노드+라우팅 일괄 저장" 전용 내부 API는 만들지 않는다. 이미 룰 콘솔이 쓰는
증분식 API가 있고, 이를 그대로 오케스트레이션하면 동일한 결과를 만들 수 있다
(GAPS.md G-15 -> 케이스 A로 확정):

    POST  /api/rules/drafts/                     빈 그래프(v1, DRAFT, scope) 생성
    POST  /api/rules/{id}/nodes/                  빈 노드 생성 (최초 생성 노드가 자동 entry)
    PATCH /api/rules/{id}/nodes/{node_key}/       condition/conditionText/action/routings 채움

인증 블로커 (GAPS.md G-16, 필독): 위 3개 엔드포인트는 `CanViewRule` 권한이
필요하다(`PolicyLookupView`/`RuleContextView`와 달리 AllowAny가 아니다). FastAPI는
로그인 세션이 없다 — 내부 서비스 인증(서비스 계정 토큰 등)이 해결되기 전까지는
`create_rule_graph_draft()` 호출이 401/403으로 실패하는 게 정상이다.
`get_eval_context_schema()`는 AllowAny라 이 블로커와 무관하게 지금 바로 동작한다.

임시 대응: `settings.django_service_token`이 설정되면 Bearer 헤더로 실어 보낸다.
Django 쪽에 이 토큰을 검증하는 인증 클래스가 아직 없으므로 팀 결정 전까지는
빈 문자열로 두고, STEP 3 ①~③(스키마 조회·검색)만으로 배선을 검증한다.
"""
from __future__ import annotations

from typing import Any

import httpx

from .settings import settings

_BASE = settings.django_internal_base
_TIMEOUT = 20.0


def _headers() -> dict[str, str]:
    token = settings.django_service_token
    return {"Authorization": f"Bearer {token}"} if token else {}


def get_eval_context_schema() -> list[str]:
    """EvalContext 허용 경로 카탈로그(v4). SoT는 Django `eval_context.py`.

    `EvalContextSchemaView`(AllowAny)만 호출 — 인증 무관, 지금 바로 동작해야 한다.
    조회 실패 시 빈 목록 반환(프롬프트에서 "허용 경로 조회 실패" 안내로 대체).
    """
    try:
        r = httpx.get(
            f"{_BASE}/api/internal/rule-agent-v0/eval-context-schema/",
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return list(r.json().get("paths", []))
    except Exception:
        return []


def create_rule_graph_draft(
    name: str,
    scope: str,
    nodes: list[dict[str, Any]],
    routings_by_node: dict[str, list[dict[str, str]]],
) -> dict[str, Any]:
    """기존 Rule 콘솔 API 3종을 순서대로 호출해 그래프+노드+라우팅을 만든다.

    nodes: agent.py `_assemble_linear_graph()`가 만든 노드 리스트. **리스트 순서 =
           생성 순서 = entry 결정 순서**다(첫 호출로 생성되는 노드가 자동으로
           `entry_node_key`가 된다 — `RuleGraphViewSet.create_node` 참조).
    routings_by_node: {node_key: [{"onResult": "MATCH"|"NO_MATCH", "toNodeKey": "..."}]}
                      camelCase 키 — 기존 `update_node` action이 `request.data`를
                      그대로 읽는 방식이라 프론트와 동일한 camelCase여야 한다.

    v0는 항상 새 계열(v1)만 만든다 — 기존 계열에 새 버전을 추가하는 것
    (`POST /api/rules/{id}/versions`)은 v1 범위(GAPS.md 참조).
    """
    headers = _headers()

    r = httpx.post(
        f"{_BASE}/api/rules/drafts/",
        json={"name": name, "scope": scope},
        headers=headers,
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    graph = r.json()
    graph_id = graph.get("id")

    created_nodes: list[str] = []
    for node in nodes:
        node_key = node["node_key"]

        r = httpx.post(
            f"{_BASE}/api/rules/{graph_id}/nodes/",
            json={"nodeKey": node_key},
            headers=headers,
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        created_nodes.append(node_key)

        r = httpx.patch(
            f"{_BASE}/api/rules/{graph_id}/nodes/{node_key}/",
            json={
                "condition": node["condition"],
                "conditionText": node["condition_text"],
                "action": node["action"],
                "routings": routings_by_node.get(node_key, []),
            },
            headers=headers,
            timeout=_TIMEOUT,
        )
        r.raise_for_status()

    return {
        "graph_id": graph_id,
        "family_key": graph.get("familyKey") or graph.get("family_key"),
        "version": graph.get("version"),
        "status": graph.get("status"),
        "created_nodes": created_nodes,
    }
