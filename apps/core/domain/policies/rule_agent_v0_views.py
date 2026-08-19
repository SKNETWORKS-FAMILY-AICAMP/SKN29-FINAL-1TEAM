# apps/core/domain/policies/rule_agent_v0_views.py
"""Rule Agent v0 전용 Django 내부 API — EvalContext 스키마 + 룰 작성 카탈로그 조회.

설계 결정: 그래프 저장용 내부 API는 새로 만들지 않는다. 기존 `RuleGraphViewSet`
(POST /api/rules/drafts/, POST /api/rules/{id}/nodes/,
PATCH /api/rules/{id}/nodes/{node_key}/)을 그대로 오케스트레이션해서 재사용한다.

이 파일엔 그 흐름이 못 채우는 것들만 남는다 — LLM 프롬프트에 넣을 EvalContext 허용
경로 목록, 그리고 decision/severity 선택지 카탈로그(엔진 소스를 그대로 노출, 2026-08-19
§8 후속 — `agent.py`/`DraftTab.tsx`가 각자 하드코딩하던 걸 하나로 합침). 기존
`PolicyLookupView`/`RuleContextView`와 동일한 패턴(AllowAny, 단일 read API)을 따른다.
"""
from __future__ import annotations

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .engine import DECISIONS_CATALOG, PASS_THROUGH, SEVERITIES_CATALOG
from .eval_context import EVAL_CONTEXT_SCHEMA_PATHS


class EvalContextSchemaView(APIView):
    """GET /api/internal/rule-agent-v0/eval-context-schema/"""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"paths": sorted(EVAL_CONTEXT_SCHEMA_PATHS)})


class ActionSchemaView(APIView):
    """GET /api/internal/rule-agent-v0/action-schema/ — decision/severity 카탈로그.

    `engine.py`가 유일한 소스(§8 후속) — AI 서비스는 이 응답을 그대로 LLM 툴 스키마의
    enum으로 쓴다(`agent.py`). 같은 값을 브라우저(룰 콘솔 화면)에도 노출해야 해서
    `RuleGraphViewSet.action_schema`(인가 필요, `rule_view`)가 이 모듈 함수를 재사용한다.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        return Response(action_schema_payload())


def action_schema_payload() -> dict:
    return {
        "decisions": list(DECISIONS_CATALOG),
        "severities": list(SEVERITIES_CATALOG),
        "passThrough": PASS_THROUGH,
    }
