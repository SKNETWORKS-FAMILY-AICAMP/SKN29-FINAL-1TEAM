"""조립기 신규 사실 회귀 — 이력 집계·영업일·조직축·첨부 종류·실사용자.

여기서 고정하는 계약 넷:

① **`None`은 모름이지 0이 아니다.** 주인을 모르는 건(공용카드 미등록)은 이력을 집계하지
   않고 비운다 — 0으로 채우면 "하루에 한 푼도 안 썼다"가 되어 한도 판정이 그대로 틀린다.

② **이력은 카드가 아니라 사람 기준이다.** 비교 대상인 `policy.position_*_limit`이 직책
   축이라 사람이어야 뜻이 맞고, 한 사람이 개인·공용 카드를 섞어 쓰면 카드 기준 합계는
   한도와 무관한 숫자가 된다.

③ **첨부는 종류별로 묻는다.** `has_supporting_evidence` 하나로는 "참석자 명단이 필요한
   지출인데 명단이 있는가"를 물을 수 없다.

④ **조립된 값은 룰이 참조할 수 있다** — 스키마에 없으면 ACTIVE 전환에서 막힌다.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from domain.accounts.models import Team
from domain.cards.models import Card
from domain.policies.context_builder import build_rule_context
from domain.policies.eval_context import EVAL_CONTEXT_SCHEMA_PATHS
from domain.settlements.attachments import Attachment, AttachmentKind
from domain.settlements.models import Settlement
from domain.transactions.models import MerchantCategory, Transaction

User = get_user_model()


class SourcingTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="영업팀", bu="영업본부")
        self.kim = User.objects.create_user("kim", password="p", team=self.team)
        self.lee = User.objects.create_user("lee", password="p", team=self.team)
        self.card = Card.objects.create(card_type="SHARED", name="공용1")
        self.now = timezone.localtime()

    # `owner`의 기본값을 sentinel로 둔다 — `None`이 "안 넘김"과 "주인 없음" 두 뜻으로
    #  쓰이면 주인 없는 건을 시험할 방법이 없다(EvalContext의 None 계약과 같은 함정).
    UNSET = object()

    def _settle(self, amount, *, merchant="김밥천국", when=None, owner=UNSET,
                actual=None, category="식대"):
        tx = Transaction.objects.create(
            card=self.card, merchant=merchant, amount=amount, ts=when or self.now,
        )
        return Settlement.objects.create(
            transaction=tx, category=category,
            submitted_by=self.kim if owner is self.UNSET else owner,
            actual_user=actual, team=self.team,
        )

    def ctx(self, settlement):
        context, _ = build_rule_context(settlement=settlement)
        return context

    # ── ① 모름과 0 ────────────────────────────────────────────────────────
    def test_주인을_모르면_이력을_지어내지_않는다(self):
        s = self._settle(30_000, owner=None)
        c = self.ctx(s)
        self.assertIsNone(c["history"]["daily_cumulative_amount"])
        self.assertIsNone(c["history"]["monthly_cumulative_amount"])
        self.assertIsNone(c["history"]["same_vendor_count"])

    def test_실사용자_미기록이면_지출자와_같은지도_모름이다(self):
        s = self._settle(30_000)
        self.assertIsNone(self.ctx(s)["card"]["actual_user_is_spender"])

    def test_실사용자가_기록되면_지출자와_같은지_판별한다(self):
        same = self._settle(30_000, actual=self.kim)
        other = self._settle(30_000, actual=self.lee)
        self.assertIs(self.ctx(same)["card"]["actual_user_is_spender"], True)
        self.assertIs(self.ctx(other)["card"]["actual_user_is_spender"], False)

    # ── ② 이력은 사람 기준 ────────────────────────────────────────────────
    def test_같은_날_누적액은_본인_것만_더한다(self):
        target = self._settle(30_000)
        self._settle(20_000)                      # 같은 사람 — 더해진다
        self._settle(50_000, owner=self.lee)      # 다른 사람 — 안 더해진다(같은 카드인데도)
        self.assertEqual(self.ctx(target)["history"]["daily_cumulative_amount"], 50_000)

    def test_월_누적은_같은_달만_더한다(self):
        target = self._settle(30_000)
        self._settle(70_000, when=self.now - timedelta(days=40))
        c = self.ctx(target)
        self.assertEqual(c["history"]["monthly_cumulative_amount"], 30_000)

    def test_최종반려_건은_집계에서_뺀다(self):
        target = self._settle(30_000)
        rejected = self._settle(90_000)
        Settlement.objects.filter(pk=rejected.pk).update(status="REJECT")
        self.assertEqual(self.ctx(target)["history"]["daily_cumulative_amount"], 30_000)

    def test_같은_가맹점_횟수를_센다(self):
        target = self._settle(10_000, merchant="김밥천국")
        self._settle(10_000, merchant="김밥천국")
        self._settle(10_000, merchant="스타벅스")
        self.assertEqual(self.ctx(target)["history"]["same_vendor_count"], 2)

    # ── 영업일 ────────────────────────────────────────────────────────────
    def test_영업일은_주말을_뺀다(self):
        s = self._settle(10_000, when=self.now - timedelta(days=14))
        days = self.ctx(s)["derived"]["business_days_since_expense"]
        self.assertEqual(days, 10)          # 2주 = 영업일 10일
        today = self._settle(10_000)
        self.assertEqual(self.ctx(today)["derived"]["business_days_since_expense"], 0)

    # ── 근무시간 ──────────────────────────────────────────────────────────
    def test_근무시간_판별(self):
        monday = (self.now - timedelta(days=self.now.weekday())).replace(hour=14, minute=0)
        night = monday.replace(hour=23)
        weekend = (monday + timedelta(days=5)).replace(hour=14)
        self.assertIs(self.ctx(self._settle(1, when=monday))["user"]["is_working_hours"], True)
        self.assertIs(self.ctx(self._settle(1, when=night))["user"]["is_working_hours"], False)
        self.assertIs(self.ctx(self._settle(1, when=weekend))["user"]["is_working_hours"], False)

    # ── ③ 첨부 종류별 ─────────────────────────────────────────────────────
    def test_첨부는_종류별로_묻는다(self):
        s = self._settle(30_000)
        Attachment.objects.create(settlement=s, kind=AttachmentKind.PARTICIPANT_LIST)
        c = self.ctx(s)
        self.assertIs(c["evidence"]["has_participant_list"], True)
        self.assertIs(c["evidence"]["has_meeting_minutes"], False)   # 확인했더니 없음
        self.assertIs(c["evidence"]["has_trip_plan"], False)
        self.assertIs(c["evidence"]["has_contract"], False)

    # ── 조직 축 ───────────────────────────────────────────────────────────
    def test_소속_팀과_본부가_실린다(self):
        c = self.ctx(self._settle(10_000))
        self.assertEqual(c["user"]["team"], "영업팀")
        self.assertEqual(c["user"]["bu"], "영업본부")

    # ── 업종 신뢰도 ───────────────────────────────────────────────────────
    def test_업종_신뢰도는_캐시에_있을_때만_실린다(self):
        self.assertIsNone(self.ctx(self._settle(10_000))["merchant"]["industry_confidence"])
        MerchantCategory.objects.create(
            normalized_name="김밥천국", industry_code="RESTAURANT",
            industry_label="일반음식점", confidence=0.42,
        )
        self.assertAlmostEqual(
            self.ctx(self._settle(10_000))["merchant"]["industry_confidence"], 0.42,
        )

    # ── ④ 스키마 계약 ─────────────────────────────────────────────────────
    def test_신규_경로가_전부_스키마에_있다(self):
        """스키마에 없으면 조립돼도 룰이 못 쓴다(ACTIVE 전환에서 막힌다)."""
        for path in (
            "user.team", "user.bu", "user.is_working_hours",
            "card.actual_user_is_spender", "merchant.industry_confidence",
            "evidence.has_meeting_minutes", "evidence.has_participant_list",
            "evidence.has_trip_plan", "evidence.has_contract",
            "history.daily_cumulative_amount", "history.monthly_cumulative_amount",
            "history.same_vendor_count", "derived.business_days_since_expense",
        ):
            with self.subTest(path=path):
                self.assertIn(path, EVAL_CONTEXT_SCHEMA_PATHS)


class PerPersonTests(TestCase):
    """인원이 없으면 1인당 환산액이 안 만들어진다 — 화면 입력칸이 없던 시절의 증상."""

    def setUp(self):
        self.user = User.objects.create_user("kim", password="p")
        self.card = Card.objects.create(card_type="PERSONAL", name="개인1", owner=self.user)

    def _settle(self, headcount):
        tx = Transaction.objects.create(
            card=self.card, merchant="식당", amount=120_000, ts=timezone.localtime(),
        )
        return Settlement.objects.create(
            transaction=tx, category="회식", submitted_by=self.user, headcount=headcount,
        )

    def test_인원을_모르면_1인당_환산액도_모름이다(self):
        ctx, _ = build_rule_context(settlement=self._settle(None))
        self.assertIsNone(ctx["tx"]["per_person_amount"])

    def test_인원이_있으면_환산된다(self):
        ctx, _ = build_rule_context(settlement=self._settle(4))
        self.assertEqual(ctx["tx"]["per_person_amount"], 30_000)

    def test_인원_0은_모름과_다르다(self):
        """`0`은 「확인했더니 없음」이다. 나눌 수 없으니 환산액은 안 만들되, 인원 자체는
        관측값으로 남아야 한다 — 룰이 `participant_count == 0`을 물을 수 있다."""
        ctx, _ = build_rule_context(settlement=self._settle(0))
        self.assertIsNone(ctx["tx"]["per_person_amount"])
        self.assertEqual(ctx["participants"]["participant_count"], 0)
