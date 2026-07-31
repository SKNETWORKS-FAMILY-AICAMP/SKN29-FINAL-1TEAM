"""외부 I/O 없는 결정론적 룰 그래프 엔진 (FR-RA-06, FR-RA-08)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .dsl import evaluate, validate_expr


DECISIONS = {"PASS", "REJECT", "REVIEW", "RETURN"}


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


def run_rule_engine(ctx: dict[str, Any], graph: dict[str, Any]) -> RuleResult:
    """스냅샷 그래프를 순회한다. 구조 오류는 보수적으로 REVIEW 처리한다."""
    try:
        validate_graph(graph)
    except (GraphValidationError, ValueError):
        return RuleResult("REVIEW", [], ["INVALID_RULE_GRAPH"], 0.0)

    nodes, routings, current = _parts(graph)
    path: list[str] = []
    flags: list[str] = []
    visited: set[str] = set()
    while current:
        if current in visited:  # validate 이후 입력 변조에 대한 방어
            return RuleResult("REVIEW", path, flags + ["RULE_GRAPH_CYCLE"], 0.0)
        visited.add(current)
        path.append(current)
        node = nodes[current]
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
        return RuleResult(decision, path, flags, 1.0)
    return RuleResult("REVIEW", path, flags + ["NO_TERMINAL_DECISION"], 0.0)
