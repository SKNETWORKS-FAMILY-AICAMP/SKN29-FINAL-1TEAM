"""외부 I/O 없는 결정론적 룰 그래프 엔진 (FR-RA-06, FR-RA-08)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .dsl import DSLValidationError, evaluate, extract_vars, resolve_path, validate_expr


DECISIONS = {"PASS", "REJECT", "REVIEW", "RETURN"}

# ── 미해소 정책값 가드 (policy-domain.md §6)
# 조립기가 별표를 스칼라로 해소하지 못하면 `policy.*`가 None으로 남고, DSL은 None 비교를
# 안전하게 False로 흡수한다(dsl.py). 그 결과 한도 룰이 **에러 없이 미발동**하고 판정은
# PASS로 보인다. 순회 경로에서 실제로 참조된 policy.* 중 미해소가 있으면 판정을 신뢰할 수
# 없으므로 REVIEW로 강등하고 플래그를 남긴다.
POLICY_PREFIX = "policy."
UNRESOLVED_FLAG = "UNRESOLVED_POLICY_VAR"
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


def policy_vars_by_node(nodes: dict[str, dict[str, Any]]) -> dict[str, tuple[str, ...]]:
    """노드별로 조건식이 참조하는 ``policy.*`` 경로를 미리 뽑아둔다(순회 중 재파싱 방지)."""
    out: dict[str, tuple[str, ...]] = {}
    for key, node in nodes.items():
        try:
            refs = extract_vars(node.get("condition", {}))
        except DSLValidationError:
            continue
        policy_refs = tuple(sorted(r for r in refs if r.startswith(POLICY_PREFIX)))
        if policy_refs:
            out[key] = policy_refs
    return out


def _finalize(decision: str, path: list[str], flags: list[str], confidence: float,
              unresolved: list[str]) -> RuleResult:
    """미해소 정책값이 있으면 판정을 신뢰할 수 없다 — REVIEW로 강등하고 사유를 남긴다."""
    if not unresolved:
        return RuleResult(decision, path, flags, confidence)
    flags = [*flags, *(f"{UNRESOLVED_FLAG}:{p[len(POLICY_PREFIX):]}" for p in sorted(set(unresolved)))]
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
    policy_vars = policy_vars_by_node(nodes)
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
        # 이 노드가 실제로 참조한 정책값만 본다 — 도달하지 않은 노드 때문에 과잉 강등하지 않는다.
        unresolved.extend(p for p in policy_vars.get(current, ()) if resolve_path(ctx, p) is None)
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
