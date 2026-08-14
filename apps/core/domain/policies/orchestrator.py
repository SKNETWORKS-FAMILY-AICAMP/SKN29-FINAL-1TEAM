"""룰 판정 오케스트레이션 (FR-RA-10, 기술명세서 §4.2(c)) — 3단 파이프라인의 ②·③.

    ① 조립   build_rule_context(settlement) → EvalContext   ← 모든 I/O는 여기서만
    ② 선택   GLOBAL 필수 게이트 → (통과 시) 계정과목별(scope=category)   ← **이 모듈**
    ③ 순회   run_rule_engine(ctx, snapshot) → decision·path·flags       ← engine.py(순수)

여기가 하는 일은 "어떤 그래프를 어떤 순서로 돌릴지 정하고, 무엇으로 판정했는지 남기는 것"
뿐이다. 판정 로직 자체는 엔진에, 데이터 접근은 조립기에 있다 — 그래야 같은
(EvalContext, 그래프 버전)이 항상 같은 판정을 낸다(FR-RA-08 재현성).

**상태 전이는 하지 않는다.** 그건 `settlements/services.judge`의 몫이다. 판정과 전이를
갈라 두면 "판정만 다시 돌려보기"(재현·감사)가 상태를 건드리지 않고 가능하다.

## 게이트가 먼저인 이유

GLOBAL은 계정과목과 무관한 필수 검사(금지업종·증빙·사전승인·기한)다. 여기서 통과가
아닌 결정이 나면 **과목별 그래프는 건너뛴다**(FR-RA-10) — 이미 사람이 봐야 할 건이
정해졌는데 과목 룰을 더 돌려 판정을 덮어쓸 이유가 없다.

## 규칙이 없으면 통과가 아니다

ACTIVE 그래프가 하나도 없으면 `REVIEW`(+`NO_ACTIVE_RULE_GRAPH`)다. "검사할 규칙이 없다"를
"검사해보니 문제없다"로 바꾸면, 룰을 아직 안 만든 회사에서 전건이 자동 통과된다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.db import transaction as db_tx

from .context_builder import build_rule_context
from .engine import RuleResult, run_rule_engine
from .eval_context import BUILDER_VERSION, EVAL_CONTEXT_SCHEMA_VERSION
from .models import RuleGraph, RuleGraphStatus, RuleHit
from .scope import GLOBAL, normalize_scope
from .snapshot import graph_snapshot

# 그래프가 없어서 판정할 수 없었음 — 통과와 구별해야 하는 상태.
NO_GRAPH_FLAG = "NO_ACTIVE_RULE_GRAPH"
# 게이트를 통과했지만 그 과목의 세부 그래프가 없음. 판정은 게이트의 PASS를 그대로 쓴다.
NO_SCOPE_GRAPH_FLAG = "NO_SCOPE_RULE_GRAPH"

PASS = "PASS"


@dataclass(frozen=True)
class GraphRun:
    """그래프 하나를 돌린 결과. `rule_hits` 한 행에 대응한다."""
    scope: str
    graph: RuleGraph
    result: RuleResult


@dataclass(frozen=True)
class JudgeResult:
    """정산 한 건의 최종 판정.

    `runs`가 비어 있으면 돌릴 ACTIVE 그래프가 없었다는 뜻이다(decision=REVIEW).
    """
    decision: str
    path: list[str]
    flags: list[str]
    scope: str
    runs: list[GraphRun] = field(default_factory=list)
    eval_context: dict[str, Any] = field(default_factory=dict)
    unresolved_policy_fields: list[str] = field(default_factory=list)

    @property
    def graph_names(self) -> list[str]:
        return [f"{run.graph.name} v{run.graph.version}" for run in self.runs]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "path": self.path,
            "flags": self.flags,
            "scope": self.scope,
            "graphs": [
                {
                    "scope": run.scope,
                    "graphId": str(run.graph.pk),
                    "name": run.graph.name,
                    "version": run.graph.version,
                    "decision": run.result.decision,
                    "path": run.result.path,
                    "flags": run.result.flags,
                }
                for run in self.runs
            ],
            "unresolvedPolicyFields": self.unresolved_policy_fields,
        }


def active_graph(scope: str) -> RuleGraph | None:
    """스코프의 ACTIVE 그래프. 스코프당 ACTIVE는 하나뿐이라는 불변식은 DB 제약이 지킨다."""
    return (
        RuleGraph.objects.filter(scope=scope, status=RuleGraphStatus.ACTIVE)
        .prefetch_related("nodes", "routings")
        .first()
    )


def scope_of(settlement) -> str:
    """정산의 계정과목 → 그래프 scope. 분류가 비어 있으면 과목별 그래프는 못 고른다."""
    category = (settlement.category or settlement.ai_category or "").strip()
    return normalize_scope(category) if category else ""


def _run(scope: str, graph: RuleGraph, ctx: dict[str, Any]) -> GraphRun:
    return GraphRun(scope=scope, graph=graph, result=run_rule_engine(ctx, graph_snapshot(graph)))


def judge(settlement, *, record: bool = True) -> JudgeResult:
    """정산 한 건을 판정한다. 상태는 바꾸지 않는다.

    ``record=False``면 `rule_hits`를 남기지 않는다 — 화면에서 "지금 규칙으로 돌리면
    어떻게 나오나"를 미리보기 할 때 감사 로그를 오염시키지 않기 위한 통로다.
    """
    ctx, unresolved = build_rule_context(settlement=settlement)
    scope = scope_of(settlement)
    runs: list[GraphRun] = []

    gate = active_graph(GLOBAL)
    if gate is not None:
        runs.append(_run(GLOBAL, gate, ctx))

    # 게이트가 통과로 끝났을 때만 과목별로 내려간다(FR-RA-10).
    gate_passed = gate is None or runs[-1].result.decision == PASS
    scope_graph = active_graph(scope) if (gate_passed and scope and scope != GLOBAL) else None
    if scope_graph is not None:
        runs.append(_run(scope, scope_graph, ctx))

    result = _combine(runs, scope, gate_passed, ctx, unresolved)
    if record:
        _record(settlement, result)
    return result


def _combine(runs: list[GraphRun], scope: str, gate_passed: bool,
             ctx: dict[str, Any], unresolved: list[str]) -> JudgeResult:
    """마지막으로 돌린 그래프의 결정이 최종 결정이다.

    게이트가 통과가 아니면 거기서 멈췄으므로 그게 마지막이고, 통과했으면 과목별 결정이
    마지막이다. 플래그는 돌린 그래프 전부에서 모은다 — 게이트에서 붙은 사유가 과목
    판정 때문에 사라지면 검토 화면에서 근거가 없어진다.
    """
    flags: list[str] = []
    path: list[str] = []
    for run in runs:
        path.extend(f"{run.scope}:{key}" for key in run.result.path)
        flags.extend(flag for flag in run.result.flags if flag not in flags)

    if not runs:
        return JudgeResult(
            decision="REVIEW", path=[], flags=[NO_GRAPH_FLAG], scope=scope,
            eval_context=ctx, unresolved_policy_fields=unresolved,
        )

    decision = runs[-1].result.decision
    # 게이트만 돌고 통과했는데 과목 그래프가 없었던 경우 — 통과는 유지하되 사실을 남긴다.
    # (판정을 뒤집지 않는 이유: GLOBAL 게이트가 필수 검사를 이미 전부 봤다.)
    if gate_passed and len(runs) == 1 and runs[0].scope == GLOBAL and scope and scope != GLOBAL:
        flags.append(NO_SCOPE_GRAPH_FLAG)

    return JudgeResult(
        decision=decision, path=path, flags=flags, scope=scope, runs=runs,
        eval_context=ctx, unresolved_policy_fields=unresolved,
    )


@db_tx.atomic
def _record(settlement, result: JudgeResult) -> None:
    """`rule_hits`에 판정 근거를 남긴다 — 그래프당 한 행.

    그래프당 한 행인 이유: "어느 그래프의 어느 노드가 이 결정을 냈는가"가 감사의 단위다.
    합쳐서 한 행에 넣으면 게이트와 과목 판정이 섞여 경로를 되짚을 수 없다.

    돌린 그래프가 없을 때도 **한 행은 남긴다**(graph=None). 판정을 시도했고 규칙이
    없었다는 사실 자체가 기록돼야 하고, 그때의 EvalContext도 보존돼야 한다.
    """
    tx = getattr(settlement, "transaction", None)
    common = {
        "transaction": tx,
        "settlement": settlement,
        "eval_context": result.eval_context,
        "eval_context_schema_version": EVAL_CONTEXT_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
    }
    if not result.runs:
        RuleHit.objects.create(
            **common, graph=None, graph_version=0, path=[],
            flags=result.flags, decision=result.decision, confidence=0.0,
        )
        return

    RuleHit.objects.bulk_create([
        RuleHit(
            **common,
            graph=run.graph,
            graph_version=run.graph.version,
            path=run.result.path,
            flags=run.result.flags,
            decision=run.result.decision,
            confidence=run.result.confidence,
        )
        for run in result.runs
    ])
