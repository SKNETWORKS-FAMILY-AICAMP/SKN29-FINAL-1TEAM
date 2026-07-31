"""룰 그래프 서비스 (기술명세서 §4.2). ACTIVE·버전관리·롤백은 그래프 단위."""
from django.db import transaction as db_tx
from django.utils import timezone

from domain.common.models import AuditLog

from .engine import validate_graph
from .eval_context import validate_graph_vars
from .models import RULE_SCOPE_CHOICES, RuleGraph, RuleGraphStatus, RuleGraphVersion, RuleNode, RuleRouting


def _snapshot(graph: RuleGraph) -> dict:
    return {
        "nodes": list(graph.nodes.values("node_key", "condition", "action", "priority")),
        "routings": list(graph.routings.values("from_node_key", "on_result", "to_node_key", "priority")),
        "entry_node_key": graph.entry_node_key,
    }


def _valid_scopes() -> set[str]:
    return {value for value, _label in RULE_SCOPE_CHOICES}


@db_tx.atomic
def create_draft_version(graph: RuleGraph, actor=None) -> RuleGraph:
    """기존 그래프 버전을 복제해 같은 계열의 다음 DRAFT 버전을 만든다."""
    versions = RuleGraph.objects.select_for_update().filter(family_key=graph.family_key)
    latest = versions.order_by("-version").first()
    next_version = (latest.version if latest else graph.version) + 1
    draft = RuleGraph.objects.create(
        family_key=graph.family_key,
        name=graph.name,
        scope=graph.scope,
        status=RuleGraphStatus.DRAFT,
        version=next_version,
        entry_node_key=graph.entry_node_key,
        source_clause=graph.source_clause,
    )
    RuleNode.objects.bulk_create([
        RuleNode(
            graph=draft,
            node_key=node.node_key,
            condition=node.condition,
            action=node.action,
            priority=node.priority,
        )
        for node in graph.nodes.all()
    ])
    RuleRouting.objects.bulk_create([
        RuleRouting(
            graph=draft,
            from_node_key=route.from_node_key,
            on_result=route.on_result,
            to_node_key=route.to_node_key,
            priority=route.priority,
        )
        for route in graph.routings.all()
    ])
    AuditLog.objects.create(
        actor=actor,
        action="rulegraph.create_version",
        target=f"rulegraph:{draft.id}",
        after={"family_key": str(draft.family_key), "version": next_version, "source_graph_id": graph.id},
    )
    return draft


@db_tx.atomic
def create_graph_draft(name: str, scope: str, actor=None) -> RuleGraph:
    """실제 정산 Category 또는 GLOBAL scope로 새 v1 그래프를 만든다."""
    if scope not in _valid_scopes():
        raise ValueError("scope는 GLOBAL 또는 정산 비용분류 값이어야 합니다.")
    graph = RuleGraph.objects.create(name=name.strip(), scope=scope, status=RuleGraphStatus.DRAFT, version=1)
    AuditLog.objects.create(
        actor=actor,
        action="rulegraph.create",
        target=f"rulegraph:{graph.id}",
        after={"family_key": str(graph.family_key), "version": 1, "scope": scope},
    )
    return graph


@db_tx.atomic
def activate(graph: RuleGraph, actor=None) -> RuleGraph:
    """승인 → ACTIVE 전이 (그래프 단위). 동일 스코프의 기존 ACTIVE는 ARCHIVED.

    자동 승인 금지: 반드시 관리자 호출로만 실행된다(FR-RV-04).
    """
    # 기존 ACTIVE를 건드리기 전에 새 그래프의 실행 가능성을 hard gate로 검증한다.
    snapshot = _snapshot(graph)
    validate_graph(snapshot)
    missing = validate_graph_vars(snapshot)
    if missing:
        raise ValueError(f"EvalContext에 정의되지 않은 경로입니다: {', '.join(sorted(missing))}")

    RuleGraph.objects.filter(scope=graph.scope, status=RuleGraphStatus.ACTIVE).exclude(pk=graph.pk).update(
        status=RuleGraphStatus.ARCHIVED
    )
    graph.status = RuleGraphStatus.ACTIVE
    graph.activated_at = timezone.now()
    graph.approved_by = actor
    graph.save(update_fields=["status", "activated_at", "approved_by"])

    RuleGraphVersion.objects.filter(graph__scope=graph.scope).update(is_active=False)
    RuleGraphVersion.objects.update_or_create(
        graph=graph, version=graph.version,
        defaults={"snapshot": snapshot, "approved_by": actor,
                  "approved_at": timezone.now(), "is_active": True},
    )
    AuditLog.objects.create(actor=actor, action="rulegraph.activate",
                            target=f"rulegraph:{graph.id}", after={"version": graph.version})
    return graph


@db_tx.atomic
def rollback(graph: RuleGraph, actor=None) -> RuleGraph:
    """같은 그래프 계열의 이전 승인 버전 행을 다시 ACTIVE로 복원 (FR-RV-05)."""
    family = RuleGraph.objects.select_for_update().filter(family_key=graph.family_key)
    prev = (
        family.filter(version__lt=graph.version, versions__approved_at__isnull=False)
        .order_by("-version")
        .distinct()
        .first()
    )
    if prev is None:
        raise ValueError("롤백할 이전 버전이 없습니다.")
    RuleGraph.objects.filter(scope=graph.scope, status=RuleGraphStatus.ACTIVE).update(status=RuleGraphStatus.ARCHIVED)
    RuleGraphVersion.objects.filter(graph__family_key=graph.family_key).update(is_active=False)
    prev.status = RuleGraphStatus.ACTIVE
    prev.activated_at = timezone.now()
    prev.approved_by = actor
    prev.save(update_fields=["status", "activated_at", "approved_by"])
    prev.versions.filter(version=prev.version).update(is_active=True)
    AuditLog.objects.create(actor=actor, action="rulegraph.rollback",
                            target=f"rulegraph:{prev.id}", after={"version": prev.version})
    return prev
