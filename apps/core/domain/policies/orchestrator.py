"""Rule Agent 판정 오케스트레이션 — GLOBAL 필수 게이트 → 계정과목별 scope 그래프 (기술 §4.2(d)).

`services.judge()`가 호출하는 단일 진입점. 이전에는 "활성 그래프가 없다고 보고" 무조건
IN_REVIEW로 보내는 placeholder였다(GAPS G-14 "orchestrator.py 미구현") — 이 모듈이 그 갭을
메운다. FR-RA-04("미매칭/저신뢰 건은 Risk Review Agent로 자동 이관")의 앞쪽 절반(Rule Agent가
실제로 판정해서 미매칭이라고 결론 내리는 것)이 이 모듈 전까지는 존재하지 않았다.

그래프 선택 순서: ① GLOBAL(scope=GLOBAL) ACTIVE 그래프가 있으면 먼저 돌린다 — PASS가 아니면
그 결과가 최종(계정과목 그래프는 안 본다). ② GLOBAL이 PASS했거나 GLOBAL 그래프 자체가 없으면
scope(=정산 비용분류 정규화값) ACTIVE 그래프를 돌린다. ③ 실행된 그래프가 하나도 없으면(둘 다
ACTIVE 그래프 없음) REVIEW로 본다 — 사람이 볼 판정 근거 자체가 없다는 뜻이라, 감추지 않고
Risk Review로 넘긴다.
"""
from __future__ import annotations

from domain.settlements.models import Settlement

from .context_builder import build_rule_context
from .engine import RuleResult, run_rule_engine
from .eval_context import BUILDER_VERSION, EVAL_CONTEXT_SCHEMA_VERSION
from .models import RuleGraph, RuleGraphStatus, RuleHit
from .scope import GLOBAL, normalize_scope

# Rule 엔진 decision → 정산 상태 (기술 §4.2, services.ALLOWED와 정합)
DECISION_TO_STATUS = {
    "PASS": "PENDING_CONFIRM",
    "REJECT": "REJECT",
    "RETURN": "RETURNED",
    "REVIEW": "IN_REVIEW",
}


def _snapshot(graph: RuleGraph) -> dict:
    return {
        "nodes": list(graph.nodes.values("node_key", "condition", "action", "priority")),
        "routings": list(graph.routings.values("from_node_key", "on_result", "to_node_key", "priority")),
        "entry_node_key": graph.entry_node_key,
    }


def _run_graph(graph: RuleGraph, ctx: dict, settlement: Settlement) -> RuleResult:
    result = run_rule_engine(ctx, _snapshot(graph))
    RuleHit.objects.create(
        transaction=settlement.transaction, settlement=settlement, graph=graph,
        graph_version=graph.version, path=result.path, eval_context=ctx,
        flags=result.flags, decision=result.decision, confidence=result.confidence,
        eval_context_schema_version=EVAL_CONTEXT_SCHEMA_VERSION, builder_version=BUILDER_VERSION,
    )
    return result


def judge_settlement(settlement: Settlement) -> str:
    """정산 1건을 판정해 목표 상태(SettlementStatus 값)를 반환한다. RuleHit은 실행된 그래프마다 남긴다."""
    ctx, _unresolved_policy_fields = build_rule_context(settlement=settlement)

    global_graph = RuleGraph.objects.filter(scope=GLOBAL, status=RuleGraphStatus.ACTIVE).first()
    if global_graph is not None:
        result = _run_graph(global_graph, ctx, settlement)
        if result.decision != "PASS":
            return DECISION_TO_STATUS[result.decision]

    scope = normalize_scope(settlement.category or settlement.ai_category)
    scope_graph = RuleGraph.objects.filter(scope=scope, status=RuleGraphStatus.ACTIVE).first()
    if scope_graph is not None:
        result = _run_graph(scope_graph, ctx, settlement)
        return DECISION_TO_STATUS[result.decision]

    # 실행된 그래프가 없음(GLOBAL도 scope도 ACTIVE 그래프 부재) — 판정 근거가 없으므로 사람 검토로.
    return "IN_REVIEW"
