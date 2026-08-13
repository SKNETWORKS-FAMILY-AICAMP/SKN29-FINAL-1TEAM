# apps/core/domain/policies/rule_agent_v0/views.py
"""Rule Agent 생성 flow용 Django 내부 API — v0 격리 서브패키지.

기존 `domain/policies/` 모듈(models.py, dsl.py, eval_context.py, scope.py 등)은
**읽기만 하고 수정하지 않는다.** 이 서브패키지를 통째로 지워도 나머지 policies
앱은 원상태 그대로 남는다.

⚠️ 임포트 심볼명은 실제 레포 기준으로 맞출 것(배선 전 필수 확인):
   - dsl.validate_expr / dsl.extract_vars
   - eval_context.EVAL_CONTEXT_SCHEMA_PATHS (v4 카탈로그 경로 집합)
   - scope.normalize_scope
   - models.RuleGraph / RuleNode / RuleRouting
"""
from __future__ import annotations

from django.db import transaction
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from domain.policies import dsl
from domain.policies.eval_context import EVAL_CONTEXT_SCHEMA_PATHS
from domain.policies.models import RuleGraph, RuleNode, RuleRouting
from domain.policies.scope import normalize_scope


class EvalContextSchemaView(APIView):
    """GET /api/internal/rule-agent-v0/eval-context-schema/

    v4 카탈로그 경로 목록. Rule Agent가 프롬프트에 주입해 미정의 경로 생성을
    사전에 줄인다. SoT는 eval_context.py 하나 — FastAPI 쪽에 사본을 두지 않는다.
    """

    authentication_classes: list = []  # 내부망 전용 — 기존 internal 뷰 인증 방식과 통일할 것(갭)
    permission_classes: list = []

    def get(self, request):
        return Response(
            {
                "paths": sorted(EVAL_CONTEXT_SCHEMA_PATHS),
                "schema_version": getattr(
                    __import__("domain.policies.eval_context", fromlist=["x"]),
                    "EVAL_CONTEXT_SCHEMA_VERSION",
                    None,
                ),
            }
        )


class RuleGraphDraftCreateView(APIView):
    """POST /api/internal/rule-agent-v0/rule-graphs/drafts/

    생성 Agent 산출물을 DRAFT로 저장. FR-RB-05: 조립된 그래프는 status=DRAFT로
    저장. ACTIVE 전환은 이 API가 아니라 기존 승인 플로우(rule_activate 권한 +
    validate_graph_vars hard gate)만 가능하다 — 이 뷰는 절대 ACTIVE를 만들지
    않는다(자동 승인 금지, FR-RV-04).

    검증 정책:
      - DSL 화이트리스트(validate_expr): hard — 불량 노드가 있으면 422 (저장 안 함)
      - EvalContext 경로: DRAFT 단계에선 report-only.
        hard gate는 ACTIVE 전환 시점(기존 구현)에 이미 걸려 있다.
    """

    authentication_classes: list = []
    permission_classes: list = []

    @transaction.atomic
    def post(self, request):
        p = request.data
        scope = normalize_scope(p.get("scope", ""))
        if not scope:
            return Response(
                {"detail": f"scope 불량: {p.get('scope')}"},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        nodes = p.get("nodes") or []
        routings = p.get("routings") or []
        entry = p.get("entry_node_key") or ""
        if not nodes or not entry:
            return Response(
                {"detail": "nodes/entry_node_key 필수"},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # --- 1) DSL hard 검증 ------------------------------------------------
        dsl_errors: dict[str, list[str]] = {}
        for n in nodes:
            errs = dsl.validate_expr(n.get("condition"))
            if errs:
                dsl_errors[n.get("node_key", "?")] = (
                    errs if isinstance(errs, list) else [str(errs)]
                )
        if dsl_errors:
            return Response(
                {"detail": "DSL 검증 실패", "errors": dsl_errors},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # --- 2) 구조 검증(라우팅 참조 무결성) --------------------------------
        node_keys = {n["node_key"] for n in nodes}
        bad_refs = [
            r
            for r in routings
            if r["from_node_key"] not in node_keys
            or (r["to_node_key"] and r["to_node_key"] not in node_keys)
        ]
        if entry not in node_keys or bad_refs:
            return Response(
                {"detail": "라우팅/엔트리 참조 무결성 실패", "bad_routings": bad_refs},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # --- 3) EvalContext 경로 report-only ---------------------------------
        referenced: set[str] = set()
        for n in nodes:
            referenced |= set(dsl.extract_vars(n["condition"]))
        missing_paths = sorted(referenced - set(EVAL_CONTEXT_SCHEMA_PATHS))

        # --- 4) 버전 결정 ----------------------------------------------------
        family_key = p.get("family_key")
        if family_key:
            last = (
                RuleGraph.objects.filter(family_key=family_key)
                .order_by("-version")
                .first()
            )
            if last is None:
                return Response(
                    {"detail": f"family_key 미존재: {family_key}"},
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            version = last.version + 1
        else:
            import uuid

            family_key = f"agentgen-{scope}-{uuid.uuid4().hex[:8]}"
            version = 1

        # --- 5) 저장 (DRAFT) --------------------------------------------------
        graph = RuleGraph.objects.create(
            family_key=family_key,
            name=p.get("name") or f"{scope} 자동생성 초안",
            scope=scope,
            status="DRAFT",
            version=version,
            entry_node_key=entry,
            # generation_meta 저장 자리가 RuleGraph에 없다면 이 인자는 빼고
            # 응답에만 반환한다(갭 — RuleGraph.generation_meta JSONField 신설은 팀 합의 필요).
        )
        for n in nodes:
            RuleNode.objects.create(
                graph=graph,
                node_key=n["node_key"],
                condition=n["condition"],
                condition_text=n.get("condition_text", ""),
                action=n.get("action") or {},
                priority=n.get("priority", 0),
            )
        for r in routings:
            RuleRouting.objects.create(
                graph=graph,
                from_node_key=r["from_node_key"],
                on_result=r["on_result"],
                to_node_key=r.get("to_node_key", ""),
                priority=r.get("priority", 0),
            )

        return Response(
            {
                "graph_id": graph.id,
                "family_key": family_key,
                "version": version,
                "status": "DRAFT",
                "validation": {
                    "dsl": "OK",
                    "structure": "OK",
                    "missing_eval_context_paths": missing_paths,
                    "note": (
                        "missing 경로가 있으면 ACTIVE 전환 게이트(validate_graph_vars)에서 "
                        "반드시 거부된다 — DRAFT에서 룰 콘솔로 수정할 것"
                    )
                    if missing_paths
                    else "",
                },
            },
            status=status.HTTP_201_CREATED,
        )
