"""업종 사실(`merchant.*`)이 정본 어휘로 조립되는지 (§7-1).

이 자리는 예전에 조용히 어긋나 있었다 — 저장값(`한식`·`주점`)과 룰 리터럴
(`주점/유흥`)·금지업종 별표 키(`유흥주점`)가 서로 다른 어휘라, 룰의 `in [...]`이 안 걸리고
별표는 `strict_keys=True`라 `null`(→ 미해소 가드 REVIEW 강등)로 떨어졌다.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from domain.cards.models import Card, CardType
from domain.settlements.models import Settlement
from domain.transactions.models import Transaction

from ..context_builder import build_rule_context
from ..tiger_tables import upsert_all


class MerchantIndustryFactTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        upsert_all()
        cls.user = get_user_model().objects.create(username="industry-tester")

    def _facts(self, *, industry: str = "", code: str = "") -> dict:
        card = Card.objects.create(card_type=CardType.PERSONAL, name="테스트카드", owner=self.user)
        tx = Transaction.objects.create(
            card=card, merchant="테스트가맹점", amount=50_000, ts=timezone.now(),
        )
        settlement = Settlement.objects.create(
            transaction=tx, category="식대", merchant_industry=industry,
            merchant_industry_code=code, purpose="테스트", submitted_by=self.user,
        )
        context, _unresolved = build_rule_context(settlement=settlement)
        return context

    def test_legacy_label_is_folded_to_canonical(self):
        """`한식`으로 저장된 옛 데이터가 룰이 비교하는 표기로 올라온다."""
        ctx = self._facts(industry="한식")
        self.assertEqual(ctx["merchant"]["merchant_type"], "일반음식점")
        self.assertTrue(ctx["merchant"]["merchant_info_resolved"])

    def test_code_wins_over_stale_label(self):
        """코드는 데이터 계약이고 라벨은 표기다 — 둘이 다르면 코드를 믿는다."""
        ctx = self._facts(industry="옛날표기", code="BAR_ENTERTAINMENT")
        self.assertEqual(ctx["merchant"]["merchant_type"], "주점/유흥")

    def test_forbidden_table_resolves_for_prohibited_industry(self):
        """금지업종 별표가 정본 라벨로 키를 잡아 `True`로 선해소된다."""
        ctx = self._facts(industry="유흥주점")            # 규정 원문 표기 → 정본으로 접힌다
        self.assertEqual(ctx["merchant"]["merchant_type"], "주점/유흥")
        self.assertIs(ctx["merchant"]["forbidden"], True)

    def test_known_but_unlisted_industry_is_not_forbidden(self):
        """목록에 없는 업종 = 금지 아님. 이건 관측 결과라 단정해도 된다."""
        ctx = self._facts(industry="카페")
        self.assertIs(ctx["merchant"]["forbidden"], False)

    def test_unknown_industry_stays_unresolved(self):
        """접히지 않는 값은 `기타`로 밀지 않는다 — 금지 여부를 단정하면 안 되는 자리다."""
        ctx = self._facts(industry="부동산중개")
        self.assertIsNone(ctx["merchant"]["merchant_type"])
        self.assertFalse(ctx["merchant"]["merchant_info_resolved"])
        self.assertIsNone(ctx["merchant"]["forbidden"])   # strict_keys → 해소하지 않는다
