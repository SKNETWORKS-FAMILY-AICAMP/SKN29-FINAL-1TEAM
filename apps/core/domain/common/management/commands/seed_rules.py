"""RULE 명세서 v1.4의 GLOBAL 게이트 + 화면 검증용 TEST 그래프를 시드한다.

근거: ``llm_wiki/법인카드_사용규정_기반_RULE_명세서.md`` §4·§8,
구성 계획: ``llm_wiki/_context/rule-seed-plan.md``.

TEST 그래프는 운영 룰이 아니라 Rule 콘솔(구조 시각화·시뮬레이션) 화면 검증용 픽스처다.
모든 노드가 ``workflow_status="WAITING"``(검증대기)이라 시뮬레이션 탭 대상으로 잡힌다.
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


# ────────────────────────────────────────────────────────────────
#  TEST 그래프 — 구조 시각화/시뮬레이션 화면 검증용 대형·비정형 픽스처
#   · 모든 노드 검증대기(WAITING) → 시뮬레이션 탭 대상
#   · 이진 분기(MATCH/NO_MATCH)·수렴(다중 부모)·레벨 건너뛰기·단말 종료·
#     라우팅 없는 리프·진입점에서 도달 불가한 고아 노드까지 한 그래프에 담는다.
#   · 순환은 넣지 않는다(사이클 그래프는 Active 전환 게이트에서 거부됨).
# ────────────────────────────────────────────────────────────────
TEST_FAMILY_KEY = uuid.UUID("0c1d7a2e-5f43-4a11-9d7c-8e2f6b0a4c31")


def _test_node(node_key: str, title: str, condition, decision: str, description: str, priority: int, **extra) -> dict:
    return {
        "node_key": node_key,
        "condition": condition,
        "action": {
            "decision": decision,
            "title": title,
            "description": description,
            "note": "TEST 픽스처 노드 — 실제 판정에 사용하지 않습니다.",
            "ai_reason": "Rule 콘솔 화면(구조 시각화·시뮬레이션) 검증을 위해 만든 테스트 노드입니다.",
            "source_clause": "TEST 픽스처 (규정 근거 없음)",
            "origin": "new",
            "workflow_status": "WAITING",
            **extra,
        },
        "priority": priority,
    }


def _branch(from_key: str, match_to: str = "", no_match_to: str = "") -> list[dict]:
    """MATCH/NO_MATCH 이진 분기. 빈 문자열은 단말(종료)."""
    return [
        {"from_node_key": from_key, "on_result": OnResult.MATCH, "to_node_key": match_to, "priority": 0},
        {"from_node_key": from_key, "on_result": OnResult.NO_MATCH, "to_node_key": no_match_to, "priority": 1},
    ]


TEST_NODES = [
    _test_node("T-00", "진입 게이트 (전체 통과)", True, "PASS_THROUGH",
               "모든 거래가 통과하는 진입 노드. 이후 분기를 두 갈래로 나눕니다.", 0, severity="INFO"),
    _test_node("T-10", "고액 결제 감지 (50만원 초과)",
               {">": [{"var": "tx.amount"}, 500000]}, "REVIEW",
               "건당 50만원을 초과한 결제를 잡아냅니다.", 1, severity="HIGH", flag="HIGH_AMOUNT"),
    _test_node("T-11", "심야·주말 결제 감지",
               {"or": [{"==": [{"var": "derived.is_late_night"}, True]}, {"==": [{"var": "derived.is_weekend"}, True]}]},
               "REVIEW", "심야 또는 주말에 발생한 결제를 잡아냅니다.", 2, severity="MEDIUM", flag="OFF_HOURS"),
    _test_node("T-20", "사전승인 누락",
               {"==": [{"var": "approval.pre_approval_obtained"}, False]}, "RETURN",
               "사전승인이 필요한데 승인 기록이 없는 건입니다.", 3, severity="HIGH", flag="PRE_APPROVAL_MISSING"),
    _test_node("T-21", "적격증빙 누락",
               {"not": {"var": "evidence.has_valid_receipt"}}, "RETURN",
               "적격증빙이 첨부되지 않은 건입니다. 두 갈래에서 함께 도달하는 수렴 노드입니다.", 4,
               severity="HIGH", flag="EVIDENCE_MISSING"),
    _test_node("T-22", "사용 목적 불명확",
               {"or": [{"==": [{"var": "evidence.purpose_missing"}, True]},
                       {"==": [{"var": "evidence.purpose_is_generic"}, True]}]}, "RETURN",
               "목적이 비어 있거나 형식적인 문구만 적힌 건입니다.", 5, severity="MEDIUM", flag="PURPOSE_UNCLEAR"),
    _test_node("T-30", "참석자 과다 (8인 초과)",
               {">": [{"var": "participants.participant_count"}, 8]}, "REVIEW",
               "참석 인원이 많아 목적·성격 확인이 필요한 건입니다.", 6, severity="MEDIUM"),
    _test_node("T-31", "외부 참석자 포함",
               {">": [{"var": "participants.external_participant_count"}, 0]}, "REVIEW",
               "외부 참석자가 포함되어 접대성 여부 판단이 필요한 건입니다.", 7, severity="MEDIUM"),
    _test_node("T-40", "동일 가맹점 3개월 5회 이상",
               {">=": [{"var": "history.same_vendor_count_3m"}, 5]}, "REVIEW",
               "같은 가맹점에서 반복 결제된 패턴입니다. 참석자 과다 갈래에서만 도달합니다.", 8,
               severity="MEDIUM", flag="REPEATED_VENDOR"),
    _test_node("T-41", "일일 누적 한도 초과",
               {">": [{"var": "history.daily_cumulative_amount"}, {"var": "policy.position_daily_limit"}]}, "REVIEW",
               "직책별 일일 한도를 넘어선 누적 사용액입니다.", 9, severity="HIGH", flag="DAILY_LIMIT_OVER"),
    _test_node("T-50", "주의 업종 결제",
               {"in": [{"var": "merchant.merchant_type"}, ["주점", "노래연습장", "골프장", "면세점"]]}, "REVIEW",
               "업무 관련성 확인이 필요한 업종입니다.", 10, severity="HIGH", flag="WATCH_MERCHANT"),
    _test_node("T-51", "법인카드 외 결제수단",
               {"!=": [{"var": "tx.payment_method"}, "법인카드"]}, "RETURN",
               "법인카드가 아닌 수단으로 결제된 건입니다.", 11, severity="MEDIUM", flag="NON_CORPORATE_CARD"),
    _test_node("T-60", "수동 검토 종결", True, "REVIEW",
               "라우팅이 없는 리프 노드 — 이 노드의 액션으로 판정이 끝납니다.", 12,
               severity="LOW", approver="회계담당"),
    _test_node("T-61", "정산 지연 (영업일 7일 초과)",
               {"==": [{"var": "derived.biz_days_over_7"}, True]}, "RETURN",
               "정산 제출이 늦어진 건입니다.", 13, severity="MEDIUM", flag="LATE_SETTLEMENT"),
    _test_node("T-70", "최종 통과 후보", True, "PASS",
               "가장 깊은 레벨의 리프 노드입니다.", 14, severity="INFO"),
    _test_node("T-90", "[고아] 분류 신뢰도 낮음",
               {"<": [{"var": "category.confidence"}, 0.5]}, "REVIEW",
               "진입 노드에서 도달할 수 없는 고아 노드입니다. 첫 행에 따로 표시됩니다.", 15, severity="LOW"),
    _test_node("T-91", "[고아] 분류 재확인 요청", True, "RETURN",
               "고아 노드에서만 도달 가능한 하위 노드입니다.", 16, severity="LOW"),
]

# 라우팅 원칙: 위반을 잡으면(MATCH) 그 노드의 판정으로 끝내거나 확인 노드로 넘기고,
#  이상이 없으면(NO_MATCH) 다음 검사로 계속 내려가 마지막에 T-70(통과)에 도달한다.
TEST_ROUTINGS = [
    *_branch("T-00", "T-10", "T-11"),
    *_branch("T-10", "T-20", "T-11"),          # 고액이면 사전승인 확인부터
    *_branch("T-11", "T-22", "T-21"),
    *_branch("T-20", "", "T-21"),              # 사전승인 누락 → 보완요청으로 종결
    *_branch("T-21", "", "T-30"),              # 증빙 누락 → 보완요청으로 종결 (수렴 노드: 부모 둘)
    *_branch("T-22", "", "T-31"),              # 목적 불명확 → 보완요청으로 종결 (+ 레벨 건너뛰기)
    *_branch("T-30", "T-40", "T-31"),
    *_branch("T-31", "T-50", "T-41"),
    *_branch("T-40", "", "T-41"),              # 반복 결제 → 검토로 종결
    *_branch("T-41", "", "T-51"),              # 한도 초과 → 검토로 종결
    *_branch("T-50", "T-60", "T-51"),          # 주의 업종 → 수동 검토 리프로
    *_branch("T-51", "", "T-61"),              # 법인카드 외 결제 → 보완요청으로 종결
    # T-60: 라우팅 없음(리프)
    *_branch("T-61", "", "T-70"),              # 정산 지연 → 보완요청, 아니면 최종 통과
    # T-70: 라우팅 없음(리프)
    *_branch("T-90", "T-91", ""),              # 고아 노드도 자기 갈래를 가진다
    # T-91: 라우팅 없음(리프)
]


def test_snapshot() -> dict:
    return {
        "entry_node_key": "T-00",
        "nodes": TEST_NODES,
        "routings": TEST_ROUTINGS,
    }


class Command(BaseCommand):
    help = "GLOBAL 게이트(R-002, R-003) v1 + 화면 검증용 TEST 그래프를 멱등 시드합니다."

    def add_arguments(self, parser):
        parser.add_argument("--no-test", action="store_true", help="TEST 그래프는 시드하지 않습니다.")

    @transaction.atomic
    def handle(self, *args, **options):
        self._seed_global()
        if options.get("no_test"):
            return
        self._seed_test_graph()

    def _seed_global(self):
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

    def _seed_test_graph(self):
        """검증대기 상태의 대형 TEST 그래프(DRAFT) — 화면 검증 전용 픽스처."""
        snapshot = test_snapshot()
        validate_graph(snapshot)  # DAG·액션·라우팅 계약 위반이면 시드 자체가 실패한다.
        missing = validate_graph_vars(snapshot)
        if missing:
            raise ValueError(f"TEST 시드가 미정의 EvalContext 경로를 참조합니다: {sorted(missing)}")

        graph, _created = RuleGraph.objects.update_or_create(
            family_key=TEST_FAMILY_KEY,
            version=1,
            defaults={
                "name": "TEST 그래프 (구조 검증용)",
                "scope": "업무활성",
                "status": RuleGraphStatus.DRAFT,
                "entry_node_key": "T-00",
                "source_clause": "TEST 픽스처 (규정 근거 없음)",
            },
        )
        graph.nodes.all().delete()
        graph.routings.all().delete()
        RuleNode.objects.bulk_create([RuleNode(graph=graph, **node) for node in TEST_NODES])
        RuleRouting.objects.bulk_create([RuleRouting(graph=graph, **route) for route in TEST_ROUTINGS])
        self.stdout.write(self.style.SUCCESS(
            f"TEST 룰 그래프 시드 완료: 노드 {len(TEST_NODES)} / 라우팅 {len(TEST_ROUTINGS)} (전부 검증대기)"
        ))
