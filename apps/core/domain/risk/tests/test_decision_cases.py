"""결정 사례 기록 → `case_history` 적재 회귀.

고정하는 계약:
  ① **다르게 판단했을 때만** 남긴다 — 일치 건까지 넣으면 검색 상위가 다수결에 묻혀
     정작 봐야 할 예외가 밀려난다.
  ② 비교 대상은 **AI 권고 우선, 없으면 룰 판정**. 룰의 `REVIEW`는 판단을 미룬 것이라
     비교 대상이 아니다(무엇과도 "다르다"고 말할 수 없다).
  ③ **사유가 없으면 남기지 않는다** — "왜 다르게 봤는지"가 사례의 핵심이다.
  ④ 본문은 **스냅샷**이다 — 정산이 나중에 바뀌어도 그때의 사실로 남는다.
  ⑤ 적재 실패가 **결정을 되돌리지 않는다**. 밀린 건 나중에 다시 올린다.
"""
from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from domain.accounts.models import Role, Team, User
from domain.cards.models import Card, CardType
from domain.policies.flags import seed_rule_flags
from domain.risk import case_index, decision_cases
from domain.risk.models import DecisionCase, RiskReview
from domain.settlements import services
from domain.settlements.models import Category, Settlement, SettlementStatus as S
from domain.transactions.models import Transaction


class DecisionCaseTests(TestCase):
    def setUp(self):
        #  플래그 라벨은 레지스트리(`RuleFlag`)에서 온다 — 안 심으면 본문에 코드가 그대로 박힌다.
        seed_rule_flags()
        self.team = Team.objects.create(name="영업팀", bu="영업본부")
        self.spender = User.objects.create_user("kim", password="pw", role=Role.EMPLOYEE,
                                                team=self.team, first_name="김영업")
        self.acc = User.objects.create_user("acc", password="pw", role=Role.ACCOUNTANT,
                                            team=self.team, first_name="박회계")
        self.card = Card.objects.create(card_type=CardType.PERSONAL, owner=self.spender)

    def _settlement(self, *, status=S.IN_REVIEW, flags=("EVIDENCE_MISSING",), decision="REVIEW"):
        tx = Transaction.objects.create(card=self.card, merchant="강남한식당",
                                        amount=Decimal("450000"), ts=timezone.now())
        return Settlement.objects.create(
            transaction=tx, submitted_by=self.spender, team=self.team, status=status,
            category=Category.ENTERTAIN, merchant_industry="일반음식점", purpose="거래처 접대",
            rule_judgement={"decision": decision, "flags": list(flags)},
        )

    def _with_ai(self, settlement, recommendation):
        return RiskReview.objects.create(settlement=settlement, anomaly_score=0.4,
                                         ai_recommendation=recommendation)

    # ① 다를 때만
    def test_AI_권고와_다르면_사례가_남는다(self):
        settlement = self._settlement()
        self._with_ai(settlement, "APPROVE")
        with patch("domain.risk.case_index.index"):
            with self.captureOnCommitCallbacks(execute=True):
                services.review(settlement, "REJECT", self.acc, "사적 사용으로 판단됨")

        case = DecisionCase.objects.get()
        self.assertEqual(case.outcome, "REJECT")
        self.assertEqual(case.expected, "APPROVE")
        self.assertEqual(case.diverged_from, DecisionCase.Source.AI)
        self.assertEqual(case.reason, "사적 사용으로 판단됨")
        self.assertEqual(case.decided_by_id, self.acc.id)

    def test_AI_권고와_같으면_사례를_남기지_않는다(self):
        """일치 건까지 넣으면 검색 상위가 「권고대로 처리함」으로 채워진다."""
        settlement = self._settlement()
        self._with_ai(settlement, "REJECT")
        with self.captureOnCommitCallbacks(execute=True):
            services.review(settlement, "REJECT", self.acc, "규정 위반")
        self.assertFalse(DecisionCase.objects.exists())

    # ② 비교 대상
    def test_AI가_없으면_룰_판정과_비교한다(self):
        """룰이 통과시킨 건을 사람이 되돌린 것도 「다르게 판단한」 사례다."""
        settlement = self._settlement(status=S.PENDING_CONFIRM, flags=(), decision="PASS")
        with patch("domain.risk.case_index.index"):
            with self.captureOnCommitCallbacks(execute=True):
                services.review(settlement, "RETURN", self.acc, "증빙이 부족합니다")

        case = DecisionCase.objects.get()
        self.assertEqual(case.diverged_from, DecisionCase.Source.RULE)
        self.assertEqual(case.expected, "APPROVE")     # 룰 PASS ↔ 사람 APPROVE
        self.assertEqual(case.rule_decision, "PASS")

    def test_룰이_검토로_미룬_건은_비교_대상이_아니다(self):
        """`REVIEW`는 판단을 미룬 것이라 무엇과도 "다르다"고 말할 수 없다."""
        settlement = self._settlement(decision="REVIEW")     # AI 없음
        with self.captureOnCommitCallbacks(execute=True):
            services.review(settlement, "REJECT", self.acc, "규정 위반")
        self.assertFalse(DecisionCase.objects.exists())

    def test_AI_권고가_룰_판정보다_우선한다(self):
        """검토를 거친 건이라면 사람이 실제로 마주한 제안은 AI 권고다."""
        settlement = self._settlement(decision="REVIEW")
        self._with_ai(settlement, "RETURN")
        with patch("domain.risk.case_index.index"):
            with self.captureOnCommitCallbacks(execute=True):
                services.review(settlement, "REJECT", self.acc, "재발 건이라 반려")
        case = DecisionCase.objects.get()
        self.assertEqual(case.diverged_from, DecisionCase.Source.AI)
        self.assertEqual(case.expected, "RETURN")

    # ③ 사유 필수
    def test_사유가_없으면_사례를_남기지_않는다(self):
        settlement = self._settlement()
        self._with_ai(settlement, "APPROVE")
        #  승인은 사유 없이도 결정할 수 있다 — 그때는 사례로 남기지 않는다.
        with self.captureOnCommitCallbacks(execute=True):
            services.review(settlement, "APPROVE", self.acc, "")
        self.assertFalse(DecisionCase.objects.exists())

    # ④ 스냅샷 본문
    def test_본문이_자체로_완결된다(self):
        """검색이 매칭하는 건 이 문장뿐이라, 상황·판단·이유가 다 들어 있어야 한다."""
        settlement = self._settlement()
        self._with_ai(settlement, "APPROVE")
        with patch("domain.risk.case_index.index"):
            with self.captureOnCommitCallbacks(execute=True):
                services.review(settlement, "REJECT", self.acc, "사적 사용으로 판단됨")

        text = DecisionCase.objects.get().text
        self.assertIn("접대", text)
        self.assertIn("450,000원", text)
        self.assertIn("강남한식당", text)
        self.assertIn("적격증빙 없음", text)        # 판정 사유가 라벨로 들어간다
        self.assertIn("AI 권고는 승인", text)
        self.assertIn("반려", text)
        self.assertIn("사적 사용으로 판단됨", text)

    def test_조사가_받침에_맞는다(self):
        """이 문장은 임베딩될 뿐 아니라 검토 화면 인용문으로도 노출된다."""
        settlement = self._settlement()
        self._with_ai(settlement, "RETURN")
        with patch("domain.risk.case_index.index"):
            with self.captureOnCommitCallbacks(execute=True):
                services.review(settlement, "REJECT", self.acc, "사후 보완 불가")
        text = DecisionCase.objects.get().text
        self.assertIn("보완요청이었으나", text)     # 받침 O
        self.assertIn("반려로", text)               # 받침 X
        self.assertNotIn("보완요청였으나", text)
        self.assertNotIn("반려으로", text)

    def test_정산이_바뀌어도_사례_본문은_그대로다(self):
        settlement = self._settlement()
        self._with_ai(settlement, "APPROVE")
        with patch("domain.risk.case_index.index"):
            with self.captureOnCommitCallbacks(execute=True):
                services.review(settlement, "RETURN", self.acc, "증빙 보완 필요")
        before = DecisionCase.objects.get().text

        settlement.transaction.merchant = "다른 가맹점"
        settlement.transaction.save(update_fields=["merchant"])
        self.assertEqual(DecisionCase.objects.get().text, before)

    def test_적재_계약이_골든_데이터와_같은_모양이다(self):
        settlement = self._settlement()
        self._with_ai(settlement, "APPROVE")
        with patch("domain.risk.case_index.index"):
            with self.captureOnCommitCallbacks(execute=True):
                services.review(settlement, "REJECT", self.acc, "사적 사용")
        payload = DecisionCase.objects.get().to_payload()
        self.assertEqual(set(payload), {"case_id", "text", "outcome", "category", "citation"})

    # ⑤ 적재
    def test_적재_성공하면_시각이_남는다(self):
        settlement = self._settlement()
        self._with_ai(settlement, "APPROVE")
        with patch("domain.risk.case_index.httpx.post") as post:
            post.return_value.raise_for_status.return_value = None
            with self.captureOnCommitCallbacks(execute=True):
                services.review(settlement, "REJECT", self.acc, "사적 사용")
        case = DecisionCase.objects.get()
        self.assertIsNotNone(case.indexed_at)
        self.assertEqual(case.index_error, "")

    def test_적재가_실패해도_결정과_사례는_남는다(self):
        settlement = self._settlement()
        self._with_ai(settlement, "APPROVE")
        with patch("domain.risk.case_index.httpx.post", side_effect=RuntimeError("ai down")):
            with self.captureOnCommitCallbacks(execute=True):
                services.review(settlement, "REJECT", self.acc, "사적 사용")
        settlement.refresh_from_db()
        self.assertEqual(settlement.status, S.REJECT)          # 결정은 확정됐다
        case = DecisionCase.objects.get()
        self.assertIsNone(case.indexed_at)
        self.assertIn("ai down", case.index_error)

    def test_밀린_사례를_다시_올릴_수_있다(self):
        settlement = self._settlement()
        self._with_ai(settlement, "APPROVE")
        with patch("domain.risk.case_index.httpx.post", side_effect=RuntimeError("ai down")):
            with self.captureOnCommitCallbacks(execute=True):
                services.review(settlement, "REJECT", self.acc, "사적 사용")

        with patch("domain.risk.case_index.httpx.post") as post:
            post.return_value.raise_for_status.return_value = None
            tried, ok = case_index.reindex_pending()
        self.assertEqual((tried, ok), (1, 1))
        self.assertIsNotNone(DecisionCase.objects.get().indexed_at)

    def test_관리자_커맨드가_밀린_건을_처리한다(self):
        settlement = self._settlement()
        self._with_ai(settlement, "APPROVE")
        with patch("domain.risk.case_index.httpx.post", side_effect=RuntimeError("x")):
            with self.captureOnCommitCallbacks(execute=True):
                services.review(settlement, "REJECT", self.acc, "사적 사용")
        with patch("domain.risk.case_index.httpx.post") as post:
            post.return_value.raise_for_status.return_value = None
            call_command("reindex_cases", verbosity=0)
        self.assertIsNotNone(DecisionCase.objects.get().indexed_at)

    def test_정산이_지워져도_사례는_남는다(self):
        """이미 임베딩돼 검색에 쓰이고 있다 — 원본이 사라졌다고 근거가 사라지면 안 된다."""
        settlement = self._settlement()
        self._with_ai(settlement, "APPROVE")
        with patch("domain.risk.case_index.index"):
            with self.captureOnCommitCallbacks(execute=True):
                services.review(settlement, "REJECT", self.acc, "사적 사용")
        settlement.decision_labels.all().delete()
        settlement.risk_reviews.all().delete()
        settlement.events.all().delete()
        settlement.delete()
        case = DecisionCase.objects.get()
        self.assertIsNone(case.settlement_id)
        self.assertTrue(case.text)

    def test_비교_대상_판별(self):
        settlement = self._settlement(decision="PASS")
        self.assertEqual(decision_cases.expected_decision(settlement),
                         ("APPROVE", DecisionCase.Source.RULE))
        self._with_ai(settlement, "RETURN")
        self.assertEqual(decision_cases.expected_decision(settlement),
                         ("RETURN", DecisionCase.Source.AI))


class DecisionCaseListApiTests(TestCase):
    """문서 관리 화면의 「결정 사례」 — **월별 묶음**.

    1건 = 1항목이면 트리가 금세 수백 줄이 되고, 전부 한 덩어리면 "언제 결정한 사례인가"를
    못 고른다. 결정은 월 단위로 몰려 검토·집계된다(팀 통계·검토 이력이 이미 이번 달 기준).
    """
    url = "/api/policy-docs/cases/"

    def setUp(self):
        seed_rule_flags()
        team = Team.objects.create(name="영업팀", bu="영업본부")
        self.acc = User.objects.create_user("acc", password="pw", role=Role.ACCOUNTANT,
                                            team=team, first_name="박회계")
        self.emp = User.objects.create_user("kim", password="pw", role=Role.EMPLOYEE, team=team)
        for i, when in enumerate([
            timezone.datetime(2026, 7, 5, 10, tzinfo=timezone.get_current_timezone()),
            timezone.datetime(2026, 8, 3, 10, tzinfo=timezone.get_current_timezone()),
            timezone.datetime(2026, 8, 20, 10, tzinfo=timezone.get_current_timezone()),
        ]):
            case = DecisionCase.objects.create(
                case_id=f"case-t{i}", category="접대", outcome="APPROVE",
                diverged_from=DecisionCase.Source.AI, expected="RETURN",
                reason=f"사유 {i}", text=f"본문 {i}", decided_by=self.acc,
                indexed_at=timezone.now() if i else None,
            )
            DecisionCase.objects.filter(pk=case.pk).update(decided_at=when)
        self.client = APIClient()
        self.client.force_authenticate(self.acc)

    def test_월별로_묶어_돌려준다(self):
        body = self.client.get(self.url).json()
        self.assertEqual([m["key"] for m in body["months"]], ["2026-08", "2026-07"])   # 최신 먼저
        self.assertEqual(body["months"][0]["count"], 2)
        self.assertEqual(body["total"], 3)

    def test_월을_고르면_그_달만_나온다(self):
        body = self.client.get(self.url, {"month": "2026-07"}).json()
        self.assertEqual(len(body["cases"]), 1)
        # 월 목록은 **항상 전체 기준** — 선택한 달만 보이면 다른 달로 넘어갈 수 없다.
        self.assertEqual(len(body["months"]), 2)

    def test_처리자와_적재_상태를_함께_낸다(self):
        """처리자는 사례를 읽는 사람의 첫 질문이고, 미적재는 검색에 안 잡힌다는 뜻이다."""
        row = self.client.get(self.url, {"month": "2026-07"}).json()["cases"][0]
        self.assertEqual(row["decidedBy"], "박회계")
        self.assertFalse(row["indexed"])
        self.assertEqual(row["expected"], "RETURN")
        self.assertEqual(row["outcome"], "APPROVE")

    def test_권한_없는_사용자는_403(self):
        c = APIClient()
        c.force_authenticate(self.emp)
        self.assertEqual(c.get(self.url).status_code, 403)
