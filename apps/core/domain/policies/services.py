"""룰 그래프 서비스 (기술명세서 §4.2). ACTIVE·버전관리·롤백은 그래프 단위."""
from django.db import transaction as db_tx
from django.utils import timezone

from domain.common.models import AuditLog

from .models import RuleGraph, RuleGraphStatus, RuleGraphVersion


def _snapshot(graph: RuleGraph) -> dict:
    return {
        "nodes": list(graph.nodes.values("node_key", "condition", "action", "priority")),
        "routings": list(graph.routings.values("from_node_key", "on_result", "to_node_key", "priority")),
        "entry_node_key": graph.entry_node_key,
    }


@db_tx.atomic
def activate(graph: RuleGraph, actor=None) -> RuleGraph:
    """승인 → ACTIVE 전이 (그래프 단위). 동일 스코프의 기존 ACTIVE는 ARCHIVED.

    자동 승인 금지: 반드시 관리자 호출로만 실행된다(FR-RV-04).
    """
    # 동일 스코프의 다른 ACTIVE 그래프는 보관 처리 (스코프당 ACTIVE 1개)
    RuleGraph.objects.filter(scope=graph.scope, status=RuleGraphStatus.ACTIVE).exclude(pk=graph.pk).update(
        status=RuleGraphStatus.ARCHIVED
    )
    graph.status = RuleGraphStatus.ACTIVE
    graph.activated_at = timezone.now()
    graph.approved_by = actor
    graph.save(update_fields=["status", "activated_at", "approved_by"])

    # 버전 스냅샷 적재 + is_active 갱신
    graph.versions.update(is_active=False)
    RuleGraphVersion.objects.update_or_create(
        graph=graph, version=graph.version,
        defaults={"snapshot": _snapshot(graph), "approved_by": actor,
                  "approved_at": timezone.now(), "is_active": True},
    )
    AuditLog.objects.create(actor=actor, action="rulegraph.activate",
                            target=f"rulegraph:{graph.id}", after={"version": graph.version})
    return graph


@db_tx.atomic
def rollback(graph: RuleGraph, actor=None) -> RuleGraph:
    """이전 승인 버전으로 즉시 복원 (FR-RV-05)."""
    prev = graph.versions.filter(version__lt=graph.version).order_by("-version").first()
    if prev is None:
        raise ValueError("롤백할 이전 버전이 없습니다.")
    graph.versions.update(is_active=False)
    prev.is_active = True
    prev.save(update_fields=["is_active"])
    graph.version = prev.version
    graph.status = RuleGraphStatus.ACTIVE
    graph.activated_at = timezone.now()
    graph.save(update_fields=["version", "status", "activated_at"])
    AuditLog.objects.create(actor=actor, action="rulegraph.rollback",
                            target=f"rulegraph:{graph.id}", after={"version": prev.version})
    return graph
