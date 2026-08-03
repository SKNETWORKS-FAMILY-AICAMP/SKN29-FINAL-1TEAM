"""룰 그래프 서비스 (기술명세서 §4.2). ACTIVE·버전관리·롤백은 그래프 단위."""
from django.db import transaction as db_tx
from django.utils import timezone

from domain.common.models import AuditLog

from .engine import validate_graph
from .eval_context import validate_graph_vars
from .models import (
    RULE_SCOPE_CHOICES, RuleGraph, RuleGraphStatus, RuleGraphVersion, RuleNode, RuleRouting, RuleTestCase,
)


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
    # 검증셋도 함께 복제한다 — 새 버전은 자기 검증셋으로 시뮬레이션한다.
    RuleTestCase.objects.bulk_create([
        RuleTestCase(
            graph=draft, key=case.key, label=case.label, merchant=case.merchant, amount=case.amount,
            category=case.category, merchant_type=case.merchant_type, payment_method=case.payment_method,
            expected=case.expected, facts=case.facts, order=case.order, created_by=actor,
        )
        for case in graph.test_cases.all()
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
def request_activation(graph: RuleGraph, comment: str, actor=None) -> RuleGraph:
    """Active 요청 — 검토자 코멘트를 남기고 승인대기(SIMULATED)로 전환한다.

    실제 ACTIVE 전환은 룰 활성 권한자가 ``activate``로 수행한다(자동 승인 금지, FR-RV-04).
    """
    if graph.status == RuleGraphStatus.ACTIVE:
        raise ValueError("이미 활성화된 그래프입니다.")
    # 승인대기는 스코프당 1건만 — 먼저 올라온 건을 승인/반려해야 다음 건을 올릴 수 있다.
    conflict = (
        RuleGraph.objects.filter(scope=graph.scope, status=RuleGraphStatus.SIMULATED)
        .exclude(pk=graph.pk).first()
    )
    if conflict is not None:
        raise ValueError(
            f"같은 분류({graph.scope})에 이미 승인대기 그래프가 있습니다: "
            f"{conflict.name} v{conflict.version}. 해당 건을 처리한 뒤 다시 요청해주세요."
        )
    graph.status = RuleGraphStatus.SIMULATED
    graph.reviewed_by = actor
    graph.reviewed_at = timezone.now()
    graph.review_comment = comment
    graph.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_comment"])
    AuditLog.objects.create(
        actor=actor, action="rulegraph.request_activation", target=f"rulegraph:{graph.id}",
        after={"version": graph.version, "comment": comment[:500]},
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
def reject_activation(graph: RuleGraph, comment: str, actor=None) -> RuleGraph:
    """Active 요청 반려 — 승인대기(SIMULATED) 그래프를 초안으로 되돌린다.

    작성자가 코멘트를 보고 고쳐서 다시 올릴 수 있도록 반려 사유를 검토 코멘트에 남긴다.
    """
    if graph.status != RuleGraphStatus.SIMULATED:
        raise ValueError("승인대기 상태의 그래프만 반려할 수 있습니다.")
    graph.status = RuleGraphStatus.DRAFT
    graph.review_comment = (
        f"### ⛔ 반려됨 ({timezone.localtime().strftime('%Y-%m-%d %H:%M')})\n\n{comment}\n\n"
        f"---\n\n{graph.review_comment}"
    ).strip()
    graph.reviewed_at = timezone.now()
    graph.save(update_fields=["status", "review_comment", "reviewed_at"])
    AuditLog.objects.create(
        actor=actor, action="rulegraph.reject_activation", target=f"rulegraph:{graph.id}",
        after={"version": graph.version, "comment": comment[:500]},
    )
    return graph


@db_tx.atomic
def rollback_to(target: RuleGraph, actor=None) -> RuleGraph:
    """지정한 과거 버전을 다시 ACTIVE로 되돌린다 (버전 이력 모달의 롤백)."""
    if target.status == RuleGraphStatus.ACTIVE:
        raise ValueError("이미 활성 버전입니다.")
    if not target.versions.filter(approved_at__isnull=False).exists():
        raise ValueError("한 번도 승인된 적 없는 버전으로는 롤백할 수 없습니다.")
    RuleGraph.objects.filter(scope=target.scope, status=RuleGraphStatus.ACTIVE).exclude(pk=target.pk).update(
        status=RuleGraphStatus.ARCHIVED
    )
    RuleGraphVersion.objects.filter(graph__family_key=target.family_key).update(is_active=False)
    target.status = RuleGraphStatus.ACTIVE
    target.activated_at = timezone.now()
    target.approved_by = actor
    target.save(update_fields=["status", "activated_at", "approved_by"])
    target.versions.filter(version=target.version).update(is_active=True)
    AuditLog.objects.create(actor=actor, action="rulegraph.rollback",
                            target=f"rulegraph:{target.id}", after={"version": target.version})
    return target


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
