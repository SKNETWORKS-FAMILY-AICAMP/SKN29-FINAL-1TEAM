"""상세 화면 수정 저장(PATCH) + 「제출하면 그 값으로 판정된다」 회귀.

## 왜 이 파일이 생겼나

상세 모달의 제목은 "정산 상세 · 수정"이었지만 **저장 경로가 아예 없었다.** 분류를 고르고
목적을 적어 제출해도 서버는 옛 값 그대로였고, 판정은 「분류 미기재」로 걸었다. 사람이
확인하고 올린 값이 판정에 닿지 않으면 확인 자체가 의미가 없다.

고정하는 계약:
  ① 화면에서 고친 값이 **저장된다** (분류·목적·업종·금액·가맹점·일자).
  ② `category`는 **사람이 확정한 값**이고 `ai_category`는 건드리지 않는다 —
     제안↔확정을 대조해야 AI 정확도를 잴 수 있다(지도학습 피드백의 원천).
  ③ 저장 후 제출하면 **그 값으로 판정된다**(EvalContext `category.value`).
  ④ 회계 검토가 시작된 뒤에는 못 고친다. 남의 건도 못 고친다.
  ⑤ 빈 분류로 확정값을 지우지 않는다 — 화면 실수로 확정 분류가 날아가면 안 된다.
"""
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from domain.accounts.models import Role, Team, User
from domain.cards.models import Card, CardType
from domain.policies import orchestrator
from domain.policies.context_builder import build_rule_context
from domain.settlements.models import Category, Settlement, SettlementStatus as S
from domain.transactions.models import Receipt, Transaction


class SettlementEditTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="영업팀", bu="영업본부")
        self.user = User.objects.create_user("kim", password="pw", role=Role.EMPLOYEE,
                                             team=self.team, first_name="김영업")
        self.other = User.objects.create_user("park", password="pw", role=Role.EMPLOYEE,
                                              team=self.team, first_name="박영업")
        self.card = Card.objects.create(card_type=CardType.PERSONAL, owner=self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _imported(self, **kwargs):
        """「내역 불러오기」가 만드는 모양 — 분류는 **AI 제안만** 있고 확정값은 비어 있다."""
        tx = Transaction.objects.create(card=self.card, merchant="스타벅스 역삼점",
                                        amount=Decimal("8000"), ts=timezone.now())
        Receipt.objects.create(matched_tx=tx, status="MATCHED", file_ref="r.jpg")
        defaults = dict(
            transaction=tx, submitted_by=self.user, team=self.team, status=S.DRAFT,
            category="", ai_category=Category.MEAL, ai_suggested=True,
            merchant_industry="카페", merchant_industry_code="CAFE", purpose="",
        )
        defaults.update(kwargs)
        return Settlement.objects.create(**defaults)

    # ① 저장된다
    def test_수정한_값이_저장된다(self):
        s = self._imported()
        r = self.client.patch(f"/api/settlements/{s.id}/", {
            "category": Category.MEAL, "purpose": "팀 오전 회의 음료",
            "merchantIndustry": "카페", "merchant": "스타벅스 삼성점", "amount": "9500",
        }, format="json")
        self.assertEqual(r.status_code, 200)
        s.refresh_from_db()
        self.assertEqual(s.category, Category.MEAL)
        self.assertEqual(s.purpose, "팀 오전 회의 음료")
        self.assertEqual(s.transaction.merchant, "스타벅스 삼성점")
        self.assertEqual(int(s.transaction.amount), 9500)

    # ② AI 제안은 보존된다
    def test_확정_분류를_저장해도_AI_제안은_남는다(self):
        """제안↔확정을 대조할 수 없게 되면 AI 정확도를 잴 방법이 사라진다."""
        s = self._imported()
        self.client.patch(f"/api/settlements/{s.id}/", {"category": Category.ENTERTAIN}, format="json")
        s.refresh_from_db()
        self.assertEqual(s.category, Category.ENTERTAIN)    # 사람이 확정
        self.assertEqual(s.ai_category, Category.MEAL)      # AI가 원래 한 말

    def test_사람이_확정하면_AI_제안_딱지가_떨어진다(self):
        """`ai_suggested`는 "사람 확인이 필요하다"는 뜻이다 — 지금 그 확인이 일어났다.

        남겨두면 `category.confidence`가 계속 0.5로 내려가 확인된 건이 저신뢰로 다시 걸린다.
        """
        s = self._imported()
        self.assertTrue(s.ai_suggested)
        self.client.patch(f"/api/settlements/{s.id}/", {"category": Category.MEAL}, format="json")
        s.refresh_from_db()
        self.assertFalse(s.ai_suggested)
        self.assertEqual(s.ai_category, Category.MEAL)   # 제안 기록은 그대로

    def test_업종은_정본_어휘로_접혀_저장된다(self):
        """이 값이 곧 `merchant.merchant_type` 판정 사실이라 표기가 갈리면 룰이 안 걸린다."""
        s = self._imported()
        self.client.patch(f"/api/settlements/{s.id}/", {"merchantIndustry": "유흥주점"}, format="json")
        s.refresh_from_db()
        self.assertEqual(s.merchant_industry, "주점/유흥")
        self.assertEqual(s.merchant_industry_code, "BAR_ENTERTAINMENT")

    def test_날짜만_고치면_결제_시각은_유지된다(self):
        """시각이 정오로 밀리면 심야 결제 판정(`derived.is_late_night`)이 조용히 뒤집힌다."""
        s = self._imported()
        s.transaction.ts = timezone.make_aware(
            timezone.datetime(2026, 8, 10, 23, 30))
        s.transaction.save(update_fields=["ts"])
        self.client.patch(f"/api/settlements/{s.id}/", {"date": "2026-08-12"}, format="json")
        s.refresh_from_db()
        local = timezone.localtime(s.transaction.ts)
        self.assertEqual(local.date().isoformat(), "2026-08-12")
        self.assertEqual((local.hour, local.minute), (23, 30))

    # ⑤ 빈 값으로 확정 분류를 지우지 않는다
    def test_빈_분류는_확정값을_지우지_않는다(self):
        s = self._imported(category=Category.MEAL)
        self.client.patch(f"/api/settlements/{s.id}/", {"category": ""}, format="json")
        s.refresh_from_db()
        self.assertEqual(s.category, Category.MEAL)

    # ④ 권한·상태 가드
    def test_남의_건은_수정할_수_없다(self):
        s = self._imported(submitted_by=self.other)
        r = self.client.patch(f"/api/settlements/{s.id}/", {"purpose": "몰래 수정"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_회계_검토가_시작되면_수정할_수_없다(self):
        s = self._imported(status=S.IN_REVIEW)
        r = self.client.patch(f"/api/settlements/{s.id}/", {"purpose": "늦은 수정"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_보완요청_받은_건은_고칠_수_있다(self):
        """고칠 수 없으면 보완요청이 의미가 없다."""
        s = self._imported(status=S.RETURNED)
        r = self.client.patch(f"/api/settlements/{s.id}/", {"purpose": "보완했습니다"}, format="json")
        self.assertEqual(r.status_code, 200)


class EditThenJudgeTests(TestCase):
    """**핵심 회귀** — 화면에서 고른 분류가 실제 판정 입력에 닿는가."""

    def setUp(self):
        call_command("seed_clean", verbosity=0)
        self.user = User.objects.get(username="kim")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        card = Card.objects.filter(card_type=CardType.PERSONAL).first()
        tx = Transaction.objects.create(card=card, merchant="스타벅스 역삼점",
                                        amount=Decimal("8000"), ts=timezone.now())
        Receipt.objects.create(matched_tx=tx, status="MATCHED", file_ref="r.jpg")
        self.settlement = Settlement.objects.create(
            transaction=tx, submitted_by=self.user, team=self.user.team, status=S.DRAFT,
            category="", ai_category=Category.MEAL, ai_suggested=True,
            merchant_industry="카페", merchant_industry_code="CAFE", purpose="",
        )

    def test_AI_제안만_있으면_분류_미기재로_걸린다(self):
        """제안은 제안일 뿐이다 — 사람이 확정하기 전엔 판정 입력이 비어 있다."""
        ctx, _ = build_rule_context(settlement=self.settlement)
        self.assertIsNone(ctx["category"]["value"])
        result = orchestrator.judge(self.settlement, record=False)
        self.assertEqual(result.decision, "REVIEW")
        self.assertIn("CATEGORY_MISSING", result.flags)

    def test_저장하면_그_값으로_판정된다(self):
        """화면이 제출 직전에 부르는 것과 같은 경로(PATCH) → 판정이 그 값을 본다."""
        self.client.patch(f"/api/settlements/{self.settlement.id}/", {
            "category": Category.MEAL, "purpose": "팀 오전 회의 음료",
        }, format="json")
        self.settlement.refresh_from_db()

        ctx, _ = build_rule_context(settlement=self.settlement)
        self.assertEqual(ctx["category"]["value"], Category.MEAL)
        result = orchestrator.judge(self.settlement, record=False)
        self.assertEqual(result.decision, "PASS")
        self.assertNotIn("CATEGORY_MISSING", result.flags)
        self.assertNotIn("PURPOSE_UNCLEAR", result.flags)
