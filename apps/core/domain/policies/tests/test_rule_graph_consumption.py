"""EvalContext **소비** 검증 — 실제 배포되는 룰 그래프가 사실을 어떻게 판정하는가.

조립(assembly)과 소비(consumption)를 분리해 테스트한다. 이 파일은 **소비**만 본다:
"이런 사실이 주어지면 이 그래프는 이렇게 판정해야 한다."

읽는 법 — 시나리오 표(`SCENARIOS`)가 곧 명세다:

    Scenario(
        "설명",
        facts   = {"tx.amount": 620_000, ...},   # ← 입력 (EvalContext dot-path)
        decision= "RETURN",                       # ← 기대 판정
        flags   = ["PRE_APPROVAL_MISSING"],       # ← 기대 사유
        path    = ["E-001", "E-002"],             # ← 기대 순회 경로
    )

`facts`에 적히지 않은 경로는 ``None``(=모름)으로 남는다. 그 경로를 룰이 참조하면
미해소 가드가 `REVIEW`로 강등하므로, **시나리오에 적힌 facts가 곧 "그 판정에 실제로 필요한
사실의 전부"** 다. 필요한 게 하나라도 빠지면 테스트가 즉시 알려준다.

DB를 쓰지 않는다(`SimpleTestCase`). 별표 값도 `policy.*`로 직접 적어 **기대값이 눈에 보이게** 한다
— 별표 조회 자체는 `test_context_builder.py`가 검증한다.
"""

from dataclasses import dataclass, field
from typing import Any

from django.test import SimpleTestCase

from domain.common.management.commands import seed_rules as seeds
from domain.policies.engine import run_rule_engine, validate_graph
from domain.policies.eval_context import EVAL_CONTEXT_SCHEMA_PATHS, empty_eval_context


# ── 픽스처 헬퍼 ──────────────────────────────────────────────────
def ctx(**facts: Any) -> dict[str, Any]:
    """dot-path 키워드로 EvalContext를 만든다. 적지 않은 경로는 None(=모름)."""
    context = empty_eval_context()
    for path, value in facts.items():
        dotted = path.replace("__", ".")
        assert dotted in EVAL_CONTEXT_SCHEMA_PATHS, f"스키마에 없는 경로: {dotted}"
        section, name = dotted.split(".", 1)
        context[section][name] = value
    return context


def graph(spec: dict, entry: str) -> dict:
    return {"entry_node_key": entry, "nodes": spec["nodes"], "routings": spec["routings"]}


@dataclass
class Scenario:
    name: str
    facts: dict[str, Any]
    decision: str
    flags: list[str] = field(default_factory=list)
    path: list[str] | None = None


class GraphScenarioMixin:
    """시나리오 표를 한 건씩 돌려 입력→출력을 대조한다."""
    graph_spec: dict
    entry: str
    scenarios: list[Scenario]

    def test_graph_structure_is_valid(self):
        validate_graph(graph(self.graph_spec, self.entry))

    def test_scenarios(self):
        snapshot = graph(self.graph_spec, self.entry)
        for case in self.scenarios:
            with self.subTest(case.name):
                result = run_rule_engine(ctx(**case.facts), snapshot)
                self.assertEqual(result.decision, case.decision, f"{case.name} — 판정")
                self.assertEqual(result.flags, case.flags, f"{case.name} — 사유 플래그")
                if case.path is not None:
                    self.assertEqual(result.path, case.path, f"{case.name} — 순회 경로")


# ════════════════════════════════════════════════════════════════
#  ① GLOBAL 공통 필수 게이트 (v3, ACTIVE)
#     R-002 금지업종 → R-003 상품권 현금 → R-004 공용카드 실사용자 → R-006 심야·휴일 → PASS
# ════════════════════════════════════════════════════════════════
CLEAN = {
    "merchant__merchant_type": "한식",
    "merchant__merchant_info_resolved": True,
    "category__item_type": "식사",
    "tx__payment_method": "법인카드",
    "card__card_type": "PERSONAL",
    "card__actual_user_recorded": True,
    "derived__is_late_night": False,
    "derived__is_weekend": False,
}
GATE_PATH = ["R-002", "R-003", "R-004", "R-006", "_GLOBAL_PASS"]


class GlobalGateTests(GraphScenarioMixin, SimpleTestCase):
    graph_spec = seeds.GLOBAL_V3
    entry = "R-002"
    scenarios = [
        Scenario(
            "정상 결제 — 전 게이트 통과",
            facts=CLEAN,
            decision="PASS", flags=[], path=GATE_PATH,
        ),
        Scenario(
            "금지업종(주점) — 첫 게이트에서 즉시 반려",
            facts={**CLEAN, "merchant__merchant_type": "주점"},
            decision="REJECT", flags=["PROHIBITED_MERCHANT"], path=["R-002"],
        ),
        Scenario(
            "상품권 현금구매 — 두 조건이 모두 맞아야 걸린다",
            facts={**CLEAN, "category__item_type": "상품권", "tx__payment_method": "현금"},
            decision="REJECT", flags=["PROHIBITED_PAYMENT_METHOD"], path=["R-002", "R-003"],
        ),
        Scenario(
            "상품권이지만 카드결제 — 걸리지 않는다",
            facts={**CLEAN, "category__item_type": "상품권"},
            decision="PASS", flags=[], path=GATE_PATH,
        ),
        Scenario(
            "공용카드인데 실사용자 미기재 — 보완요청",
            facts={**CLEAN, "card__card_type": "SHARED", "card__actual_user_recorded": False},
            decision="RETURN", flags=["ACTUAL_USER_REQUIRED"], path=["R-002", "R-003", "R-004"],
        ),
        Scenario(
            "개인카드는 실사용자 조건이 적용되지 않는다",
            facts={**CLEAN, "card__card_type": "PERSONAL", "card__actual_user_recorded": False},
            decision="PASS", flags=[], path=GATE_PATH,
        ),
        # ── R-006: 「사적사용 의심」을 입력받지 않고 사실 3개를 조합해 판단한다(스키마 v3)
        Scenario(
            "심야 + 휴일 → 사적사용 의심으로 검토",
            facts={**CLEAN, "derived__is_late_night": True, "derived__is_weekend": True},
            decision="REVIEW", flags=["PERSONAL_USE_SUSPECTED"],
            path=["R-002", "R-003", "R-004", "R-006"],
        ),
        Scenario(
            "심야 + 업종 미확인 → 같은 결론(OR 분기)",
            facts={**CLEAN, "derived__is_late_night": True,
                   "merchant__merchant_info_resolved": False},
            decision="REVIEW", flags=["PERSONAL_USE_SUSPECTED"],
            path=["R-002", "R-003", "R-004", "R-006"],
        ),
        Scenario(
            "심야지만 평일 + 업종 확인됨 → 조합이 성립하지 않아 통과",
            facts={**CLEAN, "derived__is_late_night": True},
            decision="PASS", flags=[], path=GATE_PATH,
        ),
        # ── 미해소 가드: 모르는 사실을 참조하면 통과시키지 않는다
        Scenario(
            "카드 구분을 모름 → 판정 불가로 강등",
            facts={k: v for k, v in CLEAN.items() if k != "card__card_type"},
            decision="REVIEW", flags=["UNRESOLVED_FACT:card.card_type"],
        ),
    ]


# ════════════════════════════════════════════════════════════════
#  ② 기업업무추진비 (v2, ACTIVE)
#     E-001 적격증빙 → E-002 사전승인 → E-003 청탁금지 → E-004 참석자 → PASS
# ════════════════════════════════════════════════════════════════
#  별표에서 선해소된 한도값. 기대 판정을 읽을 때 이 숫자와 대조하면 된다.
LIMITS = {
    "policy__evidence_threshold": 30_000,        # 적격증빙 필수 기준
    "policy__preapproval_threshold": 500_000,    # 사전승인 필수 기준
    "policy__kickback_limit": 30_000,            # 청탁금지 1인당 한도
}
ENTERTAIN_OK = {
    **LIMITS,
    "tx__amount": 120_000,
    "tx__per_person_amount": 30_000,
    "evidence__has_valid_receipt": True,
    "approval__pre_approval_obtained": True,
    "participants__has_kickback_law_target": False,
    "participants__participant_count": 4,
}
ENTERTAIN_PATH = ["E-001", "E-002", "E-003", "E-004", "E-PASS"]


class EntertainGraphTests(GraphScenarioMixin, SimpleTestCase):
    graph_spec = seeds.ENTERTAIN_V2
    entry = "E-001"
    scenarios = [
        Scenario(
            "12만원·증빙 있음·사전승인 있음·참석 4명 → 통과",
            facts=ENTERTAIN_OK,
            decision="PASS", flags=[], path=ENTERTAIN_PATH,
        ),
        Scenario(
            "3만원 초과인데 증빙 없음 → 보완요청 (기준 30,000)",
            facts={**ENTERTAIN_OK, "evidence__has_valid_receipt": False},
            decision="RETURN", flags=["NON_DEDUCTIBLE_RISK"], path=["E-001"],
        ),
        Scenario(
            "3만원 이하면 증빙이 없어도 이 조건엔 걸리지 않는다",
            facts={**ENTERTAIN_OK, "tx__amount": 28_000, "evidence__has_valid_receipt": False},
            decision="PASS", flags=[], path=ENTERTAIN_PATH,
        ),
        Scenario(
            "62만원·사전승인 없음 → 보완요청 (기준 500,000)",
            facts={**ENTERTAIN_OK, "tx__amount": 620_000,
                   "approval__pre_approval_obtained": False},
            decision="RETURN", flags=["PRE_APPROVAL_MISSING"], path=["E-001", "E-002"],
        ),
        Scenario(
            "62만원이지만 사전승인 있음 → 통과",
            facts={**ENTERTAIN_OK, "tx__amount": 620_000},
            decision="PASS", flags=[], path=ENTERTAIN_PATH,
        ),
        Scenario(
            "청탁금지 대상자 참석 + 1인당 5만원 → 검토 (법정 한도 30,000)",
            facts={**ENTERTAIN_OK, "participants__has_kickback_law_target": True,
                   "tx__per_person_amount": 50_000},
            decision="REVIEW", flags=["KICKBACK_LAW_RISK"], path=["E-001", "E-002", "E-003"],
        ),
        Scenario(
            "청탁금지 대상자 참석이어도 1인당 3만원 이하면 걸리지 않는다",
            facts={**ENTERTAIN_OK, "participants__has_kickback_law_target": True,
                   "tx__per_person_amount": 25_000},
            decision="PASS", flags=[], path=ENTERTAIN_PATH,
        ),
        Scenario(
            "참석 인원 0명(=명단 누락) → 보완요청",
            facts={**ENTERTAIN_OK, "participants__participant_count": 0},
            decision="RETURN", flags=["PARTICIPANT_LIST_REQUIRED"],
            path=["E-001", "E-002", "E-003", "E-004"],
        ),
        Scenario(
            "참석 인원을 아예 모름 → 0명과 다르게 취급, 판정 불가로 강등",
            facts={k: v for k, v in ENTERTAIN_OK.items() if k != "participants__participant_count"},
            decision="REVIEW", flags=["UNRESOLVED_FACT:participants.participant_count"],
        ),
        Scenario(
            "한도를 못 읽음(별표 미적재) → 통과시키지 않고 강등",
            facts={k: v for k, v in ENTERTAIN_OK.items() if k != "policy__evidence_threshold"},
            decision="REVIEW", flags=["UNRESOLVED_POLICY_VAR:evidence_threshold"],
        ),
    ]


# ════════════════════════════════════════════════════════════════
#  ③ 회식비 (v1, ACTIVE)
#     M-003 참석자 → M-001 1인당 한도 → M-002 2차 → PASS
# ════════════════════════════════════════════════════════════════
DINING_OK = {
    "policy__dining_per_person_limit": 50_000,   # 회식 1인당 한도
    "tx__per_person_amount": 32_000,
    "participants__participant_count": 8,
    "dining__is_secondary_venue": False,
}
DINING_PATH = ["M-003", "M-001", "M-002", "M-PASS"]


class DiningGraphTests(GraphScenarioMixin, SimpleTestCase):
    graph_spec = seeds.DINING_V1
    entry = "M-003"
    scenarios = [
        Scenario(
            "8명·1인당 3.2만원·1차 → 통과",
            facts=DINING_OK,
            decision="PASS", flags=[], path=DINING_PATH,
        ),
        Scenario(
            "참석자 0명 → 1인당 계산이 불가하므로 가장 먼저 막는다",
            facts={**DINING_OK, "participants__participant_count": 0},
            decision="RETURN", flags=["PARTICIPANT_LIST_REQUIRED"], path=["M-003"],
        ),
        Scenario(
            "1인당 6만원 → 한도 초과로 검토 (한도 50,000)",
            facts={**DINING_OK, "tx__per_person_amount": 60_000},
            decision="REVIEW", flags=["PER_PERSON_LIMIT_OVER"], path=["M-003", "M-001"],
        ),
        Scenario(
            "2차 결제 → 검토",
            facts={**DINING_OK, "dining__is_secondary_venue": True},
            decision="REVIEW", flags=["SECONDARY_VENUE"], path=["M-003", "M-001", "M-002"],
        ),
        Scenario(
            "한도를 올리면(개정) 같은 금액이 통과한다 — 룰 수정 없이 값만 바뀐다",
            facts={**DINING_OK, "tx__per_person_amount": 60_000,
                   "policy__dining_per_person_limit": 80_000},
            decision="PASS", flags=[], path=DINING_PATH,
        ),
    ]


# ════════════════════════════════════════════════════════════════
#  ④ 출장비 (v1, 승인대기) — 숙박 한도 1종
# ════════════════════════════════════════════════════════════════
class TripGraphTests(GraphScenarioMixin, SimpleTestCase):
    graph_spec = seeds.TRIP_V1
    entry = "T-102"
    scenarios = [
        Scenario(
            "1박 9만원 · 한도 12만원 → 통과",
            facts={"policy__lodging_limit": 120_000, "trip__lodging_amount_per_night": 90_000},
            decision="PASS", flags=[], path=["T-102", "T-PASS"],
        ),
        Scenario(
            "1박 19.3만원 → 한도 초과 보완요청",
            facts={"policy__lodging_limit": 120_000, "trip__lodging_amount_per_night": 193_000},
            decision="RETURN", flags=["LODGING_LIMIT_OVER"], path=["T-102"],
        ),
        Scenario(
            "숙박비를 모름 → 강등 (출장계획서 추출 대상)",
            facts={"policy__lodging_limit": 120_000},
            decision="REVIEW", flags=["UNRESOLVED_FACT:trip.lodging_amount_per_night"],
        ),
    ]
