"""외부 I/O 없는 결정론적 룰 그래프 엔진 (FR-RA-06, FR-RA-08)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .dsl import DSLValidationError, evaluate, extract_vars, resolve_path, validate_expr


DECISIONS = {"PASS", "REJECT", "REVIEW", "RETURN"}
PASS_THROUGH = "PASS_THROUGH"  # action.decision에 쓸 수 있는 특수값 — 아래 _finalize 참조

# ── 룰 작성 카탈로그(2026-08-19) ────────────────────────────────────────────
# `DECISIONS`(위)는 순회 종료 시 유효성 검사용 집합(순서 없음). 아래 두 튜플은
# **룰 작성 화면·Rule Agent 프롬프트가 선택지로 보여줄 카탈로그**다 — 이 엔진 모듈이
# 유일한 소스이고, 다른 곳(AI 서비스 `agent.py`, 프론트 `DraftTab.tsx`)은 이 값을
# API로 받아써야 한다(`views.py::RuleGraphViewSet.action_schema`).
#
# 이전엔 AI 서비스와 프론트가 이 목록을 각자 하드코딩해 3곳에 독립적으로 존재했다
# (지금은 값이 같아 안 드러나지만, 한쪽만 바뀌면 조용히 어긋나는 구조였다) — 단일
# 소스로 합친다(`llm_wiki/_context/rule-agent-v1-ux-upgrade-plan.md` §8 후속).
#
# severity는 엔진이 실제로 읽지 않는다(현재 engine.py 어디서도 참조 안 함) — 노드
# 작성자가 참고용으로 붙이는 메타데이터일 뿐이라 "진짜 소스"가 원래 없었다. 그래도
# 세 곳에 따로 하드코딩되어 있던 걸 하나로 모으는 의미는 있다.
DECISIONS_CATALOG = ("PASS", "REJECT", "RETURN", "REVIEW", PASS_THROUGH)
SEVERITIES_CATALOG = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")

# ── 미해소 사실 가드 (policy-domain.md §6, eval-context-sourcing.md)
#
# DSL은 None 비교를 안전하게 False로 흡수한다(dsl.py). 그래서 조립기가 채우지 못한 사실을
# 참조하는 룰은 **에러 없이 미발동**하고 판정은 PASS로 보인다. 이 "조용한 False"가 이 도메인의
# 원인 결함이었다.
#
# **계약: `None`은 "거짓"이 아니라 "모름"이다.**
#   조립기가 판단할 수 있는 사실은 반드시 명시값을 쓴다(거짓이면 `False`를 쓴다).
#   `None`이 남았다면 그건 원천 데이터가 없다는 뜻이고, 그 룰의 판정은 신뢰할 수 없다.
#
# 순회 경로에서 실제로 참조된 경로 중 `None`이 있으면 REVIEW로 강등하고 사유를 남긴다.
# 플래그를 둘로 나누는 이유는 고치는 방법이 다르기 때문이다:
#   · UNRESOLVED_POLICY_VAR — 별표(policy_tables) 미적재·룩업 실패 → 표를 채우면 해결
#   · UNRESOLVED_FACT       — SoR에 원천 데이터가 없음 → 모델·입력 화면이 필요
POLICY_PREFIX = "policy."
UNRESOLVED_POLICY_FLAG = "UNRESOLVED_POLICY_VAR"
UNRESOLVED_FACT_FLAG = "UNRESOLVED_FACT"
UNRESOLVED_FLAG = UNRESOLVED_POLICY_FLAG      # 하위 호환 별칭
# 강등 스위치. False로 두면 플래그만 남기고 판정은 그대로 둔다(시연 중 임시 완화용 — PLAN R1).
DEMOTE_ON_UNRESOLVED_POLICY = True


class GraphValidationError(ValueError):
    """그래프 구조 또는 액션이 실행 계약을 위반한 경우."""


@dataclass(frozen=True)
class RuleResult:
    decision: str
    path: list[str]
    flags: list[str]
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parts(graph: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], str]:
    nodes = {node["node_key"]: node for node in graph.get("nodes", [])}
    return nodes, graph.get("routings", []), graph.get("entry_node_key", "")


def validate_graph(graph: dict[str, Any]) -> None:
    """참조 무결성, 액션, 라우팅 중복과 DAG 조건을 검증한다."""
    nodes, routings, entry = _parts(graph)
    if not nodes or entry not in nodes:
        raise GraphValidationError("유효한 entry_node_key가 필요합니다.")
    for node in nodes.values():
        validate_expr(node.get("condition", {}))
        decision = node.get("action", {}).get("decision")
        if decision not in DECISIONS and decision != "PASS_THROUGH":
            raise GraphValidationError(f"유효하지 않은 decision입니다: {decision}")

    edges: dict[str, list[str]] = {key: [] for key in nodes}
    route_keys: set[tuple[str, str, int]] = set()
    for route in routings:
        source, target = route.get("from_node_key"), route.get("to_node_key", "")
        if source not in nodes or (target and target not in nodes):
            raise GraphValidationError("라우팅이 존재하지 않는 노드를 참조합니다.")
        route_key = (source, route.get("on_result"), route.get("priority", 0))
        if route_key in route_keys:
            raise GraphValidationError("같은 결과와 우선순위의 라우팅이 중복됩니다.")
        route_keys.add(route_key)
        if target:
            edges[source].append(target)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visiting:
            raise GraphValidationError("룰 그래프에 사이클이 있습니다.")
        if key in visited:
            return
        visiting.add(key)
        for target in edges[key]:
            visit(target)
        visiting.remove(key)
        visited.add(key)

    for key in nodes:
        visit(key)


def referenced_vars_by_node(nodes: dict[str, dict[str, Any]]) -> dict[str, tuple[str, ...]]:
    """노드별로 조건식이 참조하는 **모든** EvalContext 경로를 미리 뽑아둔다.

    순회 중 재파싱을 피하려고 미리 계산한다. 조건이 리터럴뿐인 노드는 목록에 없다.
    """
    out: dict[str, tuple[str, ...]] = {}
    for key, node in nodes.items():
        try:
            refs = extract_vars(node.get("condition", {}))
        except DSLValidationError:
            continue
        if refs:
            out[key] = tuple(sorted(refs))
    return out


# 하위 호환 별칭 — 기존 호출부는 policy.* 만 보던 이름을 썼다.
def policy_vars_by_node(nodes: dict[str, dict[str, Any]]) -> dict[str, tuple[str, ...]]:
    return {
        key: tuple(r for r in refs if r.startswith(POLICY_PREFIX))
        for key, refs in referenced_vars_by_node(nodes).items()
        if any(r.startswith(POLICY_PREFIX) for r in refs)
    }


def _unresolved_flag(path: str) -> str:
    if path.startswith(POLICY_PREFIX):
        return f"{UNRESOLVED_POLICY_FLAG}:{path[len(POLICY_PREFIX):]}"
    return f"{UNRESOLVED_FACT_FLAG}:{path}"


def _finalize(decision: str, path: list[str], flags: list[str], confidence: float,
              unresolved: list[str]) -> RuleResult:
    """참조한 사실 중 모르는 값이 있으면 판정을 신뢰할 수 없다 — REVIEW로 강등한다."""
    if not unresolved:
        return RuleResult(decision, path, flags, confidence)
    flags = [*flags, *(_unresolved_flag(p) for p in sorted(set(unresolved)))]
    if not DEMOTE_ON_UNRESOLVED_POLICY:
        return RuleResult(decision, path, flags, confidence)
    return RuleResult("REVIEW", path, flags, 0.0)


def run_rule_engine(ctx: dict[str, Any], graph: dict[str, Any]) -> RuleResult:
    """스냅샷 그래프를 순회한다. 구조 오류는 보수적으로 REVIEW 처리한다."""
    try:
        validate_graph(graph)
    except (GraphValidationError, ValueError):
        return RuleResult("REVIEW", [], ["INVALID_RULE_GRAPH"], 0.0)

    nodes, routings, current = _parts(graph)
    referenced = referenced_vars_by_node(nodes)
    unresolved: list[str] = []
    path: list[str] = []
    flags: list[str] = []
    visited: set[str] = set()
    while current:
        if current in visited:  # validate 이후 입력 변조에 대한 방어
            return RuleResult("REVIEW", path, flags + ["RULE_GRAPH_CYCLE"], 0.0)
        visited.add(current)
        path.append(current)
        node = nodes[current]
        # 이 노드가 실제로 참조한 경로만 본다 — 도달하지 않은 노드 때문에 과잉 강등하지 않는다.
        unresolved.extend(p for p in referenced.get(current, ()) if resolve_path(ctx, p) is None)
        matched = evaluate(node["condition"], ctx)
        if matched:
            flag = node.get("action", {}).get("flag")
            if flag and flag not in flags:
                flags.append(flag)
        outcome = "MATCH" if matched else "NO_MATCH"
        candidates = sorted(
            (r for r in routings if r.get("from_node_key") == current and r.get("on_result") == outcome),
            key=lambda r: r.get("priority", 0),
        )
        if candidates and candidates[0].get("to_node_key"):
            current = candidates[0]["to_node_key"]
            continue
        decision = node.get("action", {}).get("decision", "REVIEW")
        if decision == "PASS_THROUGH":
            decision = "PASS" if not candidates else "REVIEW"
        return _finalize(decision, path, flags, 1.0, unresolved)
    return _finalize("REVIEW", path, flags + ["NO_TERMINAL_DECISION"], 0.0, unresolved)
