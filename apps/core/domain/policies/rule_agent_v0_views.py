# apps/core/domain/policies/rule_agent_v0_views.py
"""Rule Agent v0 전용 Django 내부 API — 딱 1개, EvalContext 스키마 조회.

설계 결정: 그래프 저장용 내부 API는 새로 만들지 않는다. 기존 `RuleGraphViewSet`
(POST /api/rules/drafts/, POST /api/rules/{id}/nodes/,
PATCH /api/rules/{id}/nodes/{node_key}/)을 그대로 오케스트레이션해서 재사용한다.

이 파일에는 그 흐름이 못 채우는 것 하나만 남는다 — LLM 프롬프트에 넣을
EvalContext 허용 경로 목록. 기존 `PolicyLookupView`/`RuleContextView`와 동일한
패턴(AllowAny, 단일 read API)을 그대로 따른다.
"""
from __future__ import annotations

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .eval_context import EVAL_CONTEXT_SCHEMA_PATHS


class EvalContextSchemaView(APIView):
    """GET /api/internal/rule-agent-v0/eval-context-schema/"""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"paths": sorted(EVAL_CONTEXT_SCHEMA_PATHS)})
