"""EvalContext **조립** 검증 — SoR의 데이터가 판정용 사실로 어떻게 변환되는가.

조립(assembly)과 소비(consumption)를 분리해 테스트한다. 이 파일은 **조립**만 본다:
"정산·거래·첨부가 이러면 EvalContext는 이렇게 나와야 한다."
판정 결과는 `test_rule_graph_consumption.py`가 본다.

읽는 법 — 케이스 표(`CASES`)가 곧 명세다:

    Case(
        "설명",
        given  = Given(card_type="SHARED", purpose=""),   # ← 입력 (DB에 만들 정산)
        expect = {"card.actual_user_recorded": False},    # ← 기대 (EvalContext dot-path)
    )

`Given`에 적지 않은 항목은 **DB에서 null로 남는다 = "모름"**. 그래서
``expect={"participants.participant_count": None}`` 같은 기대도 의미가 있다 —
"안 물어봤으니 모른다"를 명시적으로 확인하는 것이다(거짓으로 흘러가면 조용한 오판정이 된다).

별표(`PolicyTable`)는 실제 시드(`tiger_tables.upsert_all`)를 쓴다 — 한도값이 코드에 박히지
않고 표에서 나온다는 것까지 함께 검증된다.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from domain.cards.models import Card, CardType
from domain.policies.context_builder import build_rule_context
from domain.policies.eval_context import (
    EVAL_CONTEXT_SCHEMA_PATHS, EVAL_CONTEXT_SCHEMA_VERSION,
)
from domain.policies.tiger_tables import upsert_all
from domain.settlements.models import Attachment, Settlement
from domain.transactions.models import Receipt, Transaction

# 고정 시각 — 심야·주말 파생이 달력에 흔들리지 않게 못 박는다.
WED_LUNCH = "2026-08-12 13:00"   # 수요일 낮
WED_NIGHT = "2026-08-12 23:30"   # 수요일 심야
SAT_LUNCH = "2026-08-15 12:30"   # 토요일 낮


def _aware(text: str) -> datetime:
    return timezone.make_aware(datetime.strptime(text, "%Y-%m-%d %H:%M"))


@dataclass
class Given:
    """정산 1건의 입력. **적지 않은 판정 컬럼은 null(=모름)로 남는다.**"""
    amount: int = 120_000
    merchant: str = "한우명가"
    industry: str = "한식"            # 저장 표기(정본으로 접힌다). ''이면 업종 미확인
    category: str = "접대"
    purpose: str = "거래처 미팅"
    card_type: str = CardType.PERSONAL
    ts: str = WED_LUNCH
    receipt: bool = True

    # ── 판정 입력 컬럼 (None = 안 물어봄)
    headcount: int | None = None
    external_headcount: int | None = None
    pre_approved: bool | None = None
    actual_user_recorded: bool | None = None
    item_type: str = ""
    kickback_target: bool | None = None
    is_secondary_venue: bool | None = None
    includes_alcohol: bool | None = None

    # ── 첨부: (kind, extracted dot-path dict, 추출 완료 여부)
    attachments: tuple = ()


@dataclass
class Case:
    name: str
    given: Given
    expect: dict[str, Any] = field(default_factory=dict)


# ════════════════════════════════════════════════════════════════
#  케이스 표 — 입력(given)과 기대(expect)를 나란히 읽는다
# ════════════════════════════════════════════════════════════════
CASES = [
    # ── 거래에서 바로 나오는 사실
    Case(
        "거래 기본 — 금액·시각이 그대로, 업종은 정본 어휘로 접혀 옮겨진다",
        Given(amount=452_000, industry="한식", ts=WED_LUNCH),
        expect={
            "tx.amount": 452_000,
            "tx.payment_time": "13:00",
            "tx.payment_method": "법인카드",
            "merchant.merchant_type": "일반음식점",   # 저장값 `한식` → 정본(§7-1)
            "merchant.merchant_info_resolved": True,
            "derived.is_weekend": False,
        },
    ),
    Case(
        "업종을 못 밝힘 — '모름'이 아니라 '확인 실패(False)'로 관측 결과를 남긴다",
        Given(industry=""),
        expect={"merchant.merchant_type": None, "merchant.merchant_info_resolved": False},
    ),
    Case(
        # 심야 여부는 **조립기가 판단하지 않는다**(v6) — 원자(결제 시각)만 주고 룰이
        # `payment_time >= "22:00"`으로 비교한다. 기준 시각이 회사마다 다르기 때문이다.
        "심야(23:30) 결제 — 시각만 관측하고 판단은 룰에 맡긴다",
        Given(ts=WED_NIGHT),
        expect={"tx.payment_time": "23:30", "derived.is_weekend": False},
    ),
    Case(
        "주말(토) 낮 결제 — 요일은 DSL이 못 만들어 조립기가 준다(예외③)",
        Given(ts=SAT_LUNCH),
        expect={"derived.is_weekend": True},
    ),

    # ── 증빙
    Case(
        "영수증 매칭됨 → 적격증빙 있음",
        Given(receipt=True),
        expect={"evidence.has_valid_receipt": True, "evidence.expense_purpose_missing": False},
    ),
    Case(
        "영수증 없음 + 사유 미기재",
        Given(receipt=False, purpose=""),
        expect={"evidence.has_valid_receipt": False, "evidence.expense_purpose_missing": True},
    ),

    # ── 카드 구분과 실사용자 (GLOBAL 게이트 R-004의 입력)
    Case(
        "개인카드 — 실사용자는 소유자가 곧 사용자라 항상 기록된 것으로 본다",
        Given(card_type=CardType.PERSONAL, actual_user_recorded=None),
        expect={"card.card_type": "PERSONAL", "card.actual_user_recorded": True},
    ),
    Case(
        "공용카드 + 실사용자 기재됨",
        Given(card_type=CardType.SHARED, actual_user_recorded=True),
        expect={"card.card_type": "SHARED", "card.actual_user_recorded": True},
    ),
    Case(
        "공용카드 + 실사용자 미기재 → False (보완요청 대상)",
        Given(card_type=CardType.SHARED, actual_user_recorded=False),
        expect={"card.card_type": "SHARED", "card.actual_user_recorded": False},
    ),
    Case(
        "공용카드인데 아직 안 물어봄 → None (거짓이 아니라 모름)",
        Given(card_type=CardType.SHARED, actual_user_recorded=None),
        expect={"card.card_type": "SHARED", "card.actual_user_recorded": None},
    ),

    # ── 참석 인원과 1인당 환산
    Case(
        "참석 4명 · 40만원 → 1인당 10만원 자동 환산",
        Given(amount=400_000, headcount=4, external_headcount=1),
        expect={"participants.participant_count": 4,
                "participants.external_participant_count": 1,
                "tx.per_person_amount": 100_000},
    ),
    Case(
        "참석 0명(=명단 누락) → 1인당 금액은 계산하지 않는다",
        Given(amount=400_000, headcount=0),
        expect={"participants.participant_count": 0, "tx.per_person_amount": None},
    ),
    Case(
        "인원을 안 물어봄 → 0명과 다르게 None으로 남는다",
        Given(amount=400_000, headcount=None),
        expect={"participants.participant_count": None, "tx.per_person_amount": None},
    ),

    # ── 나머지 판정 컬럼
    Case(
        "사전승인·청탁금지·회식 속성이 그대로 옮겨진다",
        Given(pre_approved=False, kickback_target=True,
              is_secondary_venue=True, includes_alcohol=False, item_type="식사"),
        expect={"approval.pre_approval_obtained": False,
                "participants.has_kickback_law_target": True,
                "dining.is_secondary_venue": True,
                "dining.includes_alcohol": False,
                "category.item_type": "식사"},
    ),

    # ── 첨부 문서 추출 (증빙자료 추출 Agent가 채우는 자리)
    Case(
        "회의록에서 참석자 추출 → 컬럼이 비어 있어도 사실이 채워진다",
        Given(headcount=None,
              attachments=(("MEETING_MINUTES",
                            {"participants.participant_count": 6,
                             "participants.external_participant_count": 2}, True),)),
        expect={"participants.participant_count": 6,
                "participants.external_participant_count": 2},
    ),
    Case(
        "화면 입력이 추출값을 이긴다 (사람이 확정한 값 우선)",
        Given(headcount=9,
              attachments=(("MEETING_MINUTES", {"participants.participant_count": 6}, True),)),
        expect={"participants.participant_count": 9},
    ),
    Case(
        "사전승인 문서 추출 → 승인 여부가 채워진다",
        Given(pre_approved=None,
              attachments=(("PRE_APPROVAL", {"approval.pre_approval_obtained": True}, True),)),
        expect={"approval.pre_approval_obtained": True},
    ),
    Case(
        "추출 미완료(PENDING) 첨부는 반영하지 않는다",
        Given(headcount=None,
              attachments=(("MEETING_MINUTES", {"participants.participant_count": 6}, False),)),
        expect={"participants.participant_count": None},
    ),
    Case(
        "출장계획서 추출 — 스키마 밖 경로(flight_class)는 조용히 버린다",
        Given(category="출장",
              attachments=(("TRIP_PLAN",
                            {"trip.trip_type": "국내", "trip.region_grade": "B",
                             "trip.lodging_amount_per_night": 193_000,
                             "trip.flight_class": "BUSINESS"}, True),)),
        expect={"trip.trip_type": "국내", "trip.region_grade": "B",
                "trip.lodging_amount_per_night": 193_000},
    ),
    Case(
        # `has_supporting_evidence` 하나로 접지 않는다(v6) — 종류별 불린의 `or`로 룰이
        # 조합한다. "명단이 필요한 지출인데 명단이 있는가"를 물으려면 종류가 필요하다.
        "회의록 첨부 — 종류별로 관측한다",
        Given(attachments=(("MEETING_MINUTES", {}, True),)),
        expect={"evidence.has_meeting_minutes": True,
                "evidence.has_participant_list": False},
    ),
    Case(
        "영수증만 있으면 다른 종류는 전부 '확인했더니 없음'",
        Given(attachments=(("RECEIPT", {}, True),)),
        expect={"evidence.has_meeting_minutes": False, "evidence.has_trip_plan": False},
    ),

    # ── 별표 선해소 (PolicyTable → policy.*)
    Case(
        "별표에서 한도가 선해소돼 스칼라로 들어온다",
        Given(),
        expect={"policy.evidence_threshold": 30_000,
                "policy.preapproval_threshold": 300_000,
                "policy.dining_per_person_limit": 50_000,
                "policy.kickback_limit": 30_000,
                "policy.settlement_deadline_days": 7},
    ),
    Case(
        "금지업종 목록도 별표에서 불린으로 선해소된다",
        Given(industry="유흥주점"),      # 규정 원문 표기 → 정본 `주점/유흥`으로 접힌다
        expect={"merchant.merchant_type": "주점/유흥", "merchant.forbidden": True},
    ),
    Case(
        "금지 목록에 없는 업종 → False",
        Given(industry="한식"),
        expect={"merchant.forbidden": False},
    ),
    Case(
        "업종을 못 밝힘 → 금지 여부는 '모름'(단정하지 않는다)",
        Given(industry=""),
        expect={"merchant.forbidden": None},
    ),
]


# ════════════════════════════════════════════════════════════════
#  충돌 케이스 — 같은 경로에 서로 다른 값이 도착하면?
#    RANK_SOR(원장) > RANK_INPUT(화면 입력) > RANK_EXTRACT(문서 추출)
#    · 순위가 다르면 높은 쪽이 이기고, 진 값은 충돌로 기록된다
#    · 순위가 같은데 값이 다르면 **어느 쪽도 쓰지 않는다**(None) → 미해소 가드가 REVIEW로 보낸다
# ════════════════════════════════════════════════════════════════
CONFLICT_CASES = [
    Case(
        "회의록 4명 vs 참석자명단 6명 — 동순위 불일치는 '모름'으로 남는다",
        Given(headcount=None, attachments=(
            ("MEETING_MINUTES", {"participants.participant_count": 4}, True),
            ("PARTICIPANT_LIST", {"participants.participant_count": 6}, True),
        )),
        expect={
            "participants.participant_count": None,
            "conflicts.participants.participant_count.resolution": "dropped_as_unknown",
        },
    ),
    Case(
        "두 문서가 같은 값이면 충돌이 아니다",
        Given(headcount=None, attachments=(
            ("MEETING_MINUTES", {"participants.participant_count": 4}, True),
            ("PARTICIPANT_LIST", {"participants.participant_count": 4}, True),
        )),
        expect={"participants.participant_count": 4,
                "conflicts.participants.participant_count": None},
    ),
    Case(
        "사용자 입력이 추출값과 다르면 — 입력이 이기고 불일치는 기록된다",
        Given(headcount=9, attachments=(
            ("MEETING_MINUTES", {"participants.participant_count": 4}, True),
        )),
        expect={
            "participants.participant_count": 9,
            "conflicts.participants.participant_count.kept": 9,
            "conflicts.participants.participant_count.resolution": "input_wins",
        },
    ),
    Case(
        "사용자가 두 문서의 충돌을 해소한다 — 상위 순위가 오면 되살아난다",
        Given(headcount=7, attachments=(
            ("MEETING_MINUTES", {"participants.participant_count": 4}, True),
            ("PARTICIPANT_LIST", {"participants.participant_count": 6}, True),
        )),
        expect={"participants.participant_count": 7,
                "conflicts.participants.participant_count.resolution": "input_wins"},
    ),
    Case(
        "영수증 추출 금액이 카드 전표와 다르면 — 원장이 이기고 불일치를 남긴다",
        Given(amount=452_000, attachments=(
            ("RECEIPT", {"tx.amount": 500_000}, True),
        )),
        expect={"tx.amount": 452_000,
                "conflicts.tx.amount.kept": 452_000,
                "conflicts.tx.amount.resolution": "sor_wins"},
    ),
    Case(
        "1인당 금액은 합쳐진 인원으로 계산한다 — 추출 인원만 있어도 파생된다",
        Given(amount=400_000, headcount=None, attachments=(
            ("MEETING_MINUTES", {"participants.participant_count": 5}, True),
        )),
        expect={"participants.participant_count": 5, "tx.per_person_amount": 80_000},
    ),
    Case(
        "인원이 충돌해 '모름'이면 1인당 금액도 계산하지 않는다",
        Given(amount=400_000, headcount=None, attachments=(
            ("MEETING_MINUTES", {"participants.participant_count": 4}, True),
            ("PARTICIPANT_LIST", {"participants.participant_count": 5}, True),
        )),
        expect={"participants.participant_count": None, "tx.per_person_amount": None},
    ),
]


class EvalContextAssemblyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        upsert_all()          # 규정 별표(PolicyTable) 적재
        cls.user = get_user_model().objects.create(username="tester")

    def _build(self, given: Given) -> dict[str, Any]:
        card = Card.objects.create(card_type=given.card_type, name="테스트카드", owner=self.user)
        tx = Transaction.objects.create(
            card=card, merchant=given.merchant, amount=given.amount, ts=_aware(given.ts),
        )
        if given.receipt:
            Receipt.objects.create(matched_tx=tx, status=Receipt.Status.MATCHED)
        settlement = Settlement.objects.create(
            transaction=tx, category=given.category, merchant_industry=given.industry,
            purpose=given.purpose, submitted_by=self.user,
            headcount=given.headcount, external_headcount=given.external_headcount,
            pre_approved=given.pre_approved, actual_user_recorded=given.actual_user_recorded,
            item_type=given.item_type, kickback_target=given.kickback_target,
            is_secondary_venue=given.is_secondary_venue, includes_alcohol=given.includes_alcohol,
        )
        for kind, extracted, done in given.attachments:
            Attachment.objects.create(
                settlement=settlement, kind=kind, extracted=extracted,
                extraction_status="DONE" if done else "PENDING",
                extracted_at=timezone.now() if done else None,
            )
        context, _unresolved = build_rule_context(settlement=settlement)
        return context

    #: 충돌 기록의 속성 이름 — 기대 경로 `conflicts.<dot-path>.<속성>`을 분해할 때 쓴다.
    CONFLICT_ATTRS = {"kept", "kept_from", "resolution", "dropped"}

    def _actual(self, context: dict[str, Any], path: str) -> Any:
        """기대 경로를 실제 값으로 푼다.

        `conflicts.*`는 키 자체가 dot-path("participants.participant_count")라
        단순 분할로는 풀 수 없다 — 마지막 조각이 속성이면 떼어내고 나머지를 키로 본다.
        """
        if path.startswith("conflicts."):
            rest = path[len("conflicts."):]
            parts = rest.split(".")
            if parts[-1] in self.CONFLICT_ATTRS:
                entry = context["conflicts"].get(".".join(parts[:-1]))
                return entry.get(parts[-1]) if entry else None
            return context["conflicts"].get(rest)

        self.assertIn(path, EVAL_CONTEXT_SCHEMA_PATHS, f"스키마에 없는 경로: {path}")
        section, name = path.split(".", 1)
        return context[section][name]

    def _run(self, cases: list[Case]) -> None:
        for case in cases:
            with self.subTest(case.name):
                context = self._build(case.given)
                for path, expected in case.expect.items():
                    self.assertEqual(self._actual(context, path), expected,
                                     f"{case.name} — {path}")

    def test_cases(self):
        self._run(CASES)

    def test_conflict_cases(self):
        """출처가 다른 값이 충돌할 때의 해소 규칙."""
        self._run(CONFLICT_CASES)

    def test_meta_records_schema_and_builder_version(self):
        """스냅샷이 어느 스키마·조립기로 만들어졌는지 남는다(재현·감사)."""
        context = self._build(Given())
        self.assertEqual(context["meta"]["schema_version"], EVAL_CONTEXT_SCHEMA_VERSION)
        self.assertTrue(context["meta"]["builder_version"])
        self.assertTrue(context["meta"]["built_at"])
        self.assertIsNotNone(context["meta"]["settlement_id"])

    def test_used_tables_are_snapshotted_for_audit(self):
        """판정에 쓴 별표 원본을 남겨 '어떤 한도표로 판정했나'를 되짚을 수 있다."""
        context = self._build(Given())
        self.assertIn("evidence_threshold_table", context["tables"])
        self.assertEqual(context["tables"]["evidence_threshold_table"], {"*": 30_000})

    def test_unresolved_report_lists_only_missing_policy(self):
        """별표가 전부 적재돼 있으면 한도(policy.*)는 전부 해소된다.

        단 `merchant.forbidden`은 업종을 모르면 일부러 해소하지 않는다 — 그게 이 케이스다.
        """
        card = Card.objects.create(card_type=CardType.PERSONAL, name="c", owner=self.user)
        tx = Transaction.objects.create(card=card, merchant="m", amount=1000, ts=timezone.now())
        settlement = Settlement.objects.create(transaction=tx, submitted_by=self.user)
        _context, unresolved = build_rule_context(settlement=settlement)
        self.assertEqual(unresolved, ["merchant.forbidden"])
