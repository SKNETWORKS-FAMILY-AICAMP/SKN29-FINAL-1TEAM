"""RULE 명세서 v1.4의 GLOBAL 게이트만 시드한다.

근거: ``llm_wiki/법인카드_사용규정_기반_RULE_명세서.md`` §4·§8,
구성 계획: ``llm_wiki/_context/rule-seed-plan.md``.
"""

import uuid

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from domain.policies.engine import validate_graph
from domain.policies.eval_context import validate_graph_vars
from domain.policies.models import (
    OnResult,
    RuleGraph,
    RuleGraphStatus,
    RuleGraphVersion,
    RuleNode,
    RuleRouting,
)


GLOBAL_FAMILY_KEY = uuid.UUID("66df750e-26b3-4c9f-8af4-721a11c245f1")

GLOBAL_NODES = [
    {
        "node_key": "R-002",
        "condition": {
            "in": [
                {"var": "merchant.merchant_type"},
                ["유흥업소", "사행성업종"],
            ]
        },
        "action": {
            "decision": "REJECT",
            "severity": "CRITICAL",
            "flag": "PROHIBITED_MERCHANT",
            "title": "금지업종·사행성업종 사용 (공통)",
            "description": "카테고리 분류 전에 금지 업종 결제를 차단하는 최우선 공통 게이트입니다.",
            "note": "유흥·사행성 업종 결제는 자동 반려 후보로 표시하고 관리자가 최종 확인합니다.",
            "ai_reason": "법인카드 사용 규정 제9조②의 사용 금지 업종을 결정론적으로 선판정하기 위해 생성했습니다.",
            "source_clause": "TIGER-REG-2026-003 제9조②",
            "approver": "관리자(최종 확정)",
            "workflow_status": "ACTIVE",
        },
        "priority": 0,
    },
    {
        "node_key": "R-003",
        "condition": {
            "and": [
                {"==": [{"var": "category.item_type"}, "상품권"]},
                {"==": [{"var": "tx.payment_method"}, "현금"]},
            ]
        },
        "action": {
            "decision": "REJECT",
            "severity": "CRITICAL",
            "flag": "PROHIBITED_PAYMENT_METHOD",
            "title": "상품권 등 유가증권 현금구매 (공통)",
            "description": "상품권 등 유가증권을 현금으로 구입한 거래를 카테고리와 무관하게 탐지합니다.",
            "note": "현금 구매는 적격증빙 확보 원칙에 어긋나므로 자동 반려 후보로 표시합니다.",
            "ai_reason": "법인카드 사용 규정 제9조③의 유가증권 현금 구매 금지 조건을 실행 가능한 DSL로 변환했습니다.",
            "source_clause": "TIGER-REG-2026-003 제9조③",
            "approver": "관리자(최종 확정)",
            "workflow_status": "ACTIVE",
        },
        "priority": 1,
    },
    {
        "node_key": "_GLOBAL_PASS",
        "condition": True,
        "action": {
            "decision": "PASS",
            "title": "GLOBAL 게이트 통과",
            "description": "앞선 공통 금지 조건에 해당하지 않은 거래를 카테고리별 그래프로 전달합니다.",
            "note": "GLOBAL 검사를 통과했으며 이후 비용분류별 세부 룰을 평가합니다.",
            "ai_reason": "R-002와 R-003이 모두 불일치할 때 명시적으로 PASS를 반환하기 위한 내부 종단 노드입니다.",
            "source_clause": "RULE 명세서 §8 GLOBAL 게이트 실행 순서",
            "workflow_status": "ACTIVE",
        },
        "priority": 2,
    },
]

GLOBAL_ROUTINGS = [
    {
        "from_node_key": "R-002",
        "on_result": OnResult.NO_MATCH,
        "to_node_key": "R-003",
        "priority": 0,
    },
    {
        "from_node_key": "R-003",
        "on_result": OnResult.NO_MATCH,
        "to_node_key": "_GLOBAL_PASS",
        "priority": 0,
    },
]


def global_snapshot() -> dict:
    return {
        "entry_node_key": "R-002",
        "nodes": GLOBAL_NODES,
        "routings": GLOBAL_ROUTINGS,
    }


class Command(BaseCommand):
    help = "RULE 명세서 v1.4의 GLOBAL 게이트(R-002, R-003) v1을 멱등 시드합니다."

    @transaction.atomic
    def handle(self, *args, **options):
        snapshot = global_snapshot()
        validate_graph(snapshot)
        missing = validate_graph_vars(snapshot)
        if missing:
            raise ValueError(f"GLOBAL 시드가 미정의 EvalContext 경로를 참조합니다: {sorted(missing)}")

        # DB의 scope별 ACTIVE 단일성 제약을 만족하도록 기존 GLOBAL ACTIVE를 먼저 보관한다.
        RuleGraph.objects.filter(scope="GLOBAL", status=RuleGraphStatus.ACTIVE).exclude(
            family_key=GLOBAL_FAMILY_KEY, version=1
        ).update(status=RuleGraphStatus.ARCHIVED)

        graph, _created = RuleGraph.objects.update_or_create(
            family_key=GLOBAL_FAMILY_KEY,
            version=1,
            defaults={
                "name": "법인카드 공통 필수 게이트",
                "scope": "GLOBAL",
                "status": RuleGraphStatus.ACTIVE,
                "entry_node_key": "R-002",
                "source_clause": "TIGER-REG-2026-003 제9조②·③",
                "activated_at": timezone.now(),
            },
        )
        graph.nodes.all().delete()
        graph.routings.all().delete()
        RuleNode.objects.bulk_create([RuleNode(graph=graph, **node) for node in GLOBAL_NODES])
        RuleRouting.objects.bulk_create([RuleRouting(graph=graph, **route) for route in GLOBAL_ROUTINGS])
        RuleGraphVersion.objects.filter(graph__scope="GLOBAL").update(is_active=False)
        RuleGraphVersion.objects.update_or_create(
            graph=graph,
            version=1,
            defaults={"snapshot": snapshot, "approved_at": timezone.now(), "is_active": True},
        )
        self.stdout.write(self.style.SUCCESS("GLOBAL 룰 그래프 v1 시드 완료: R-002, R-003"))
