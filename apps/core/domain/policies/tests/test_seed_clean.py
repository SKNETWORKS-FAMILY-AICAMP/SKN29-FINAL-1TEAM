"""`seed_clean` 회귀 — 시연용 초기 상태와 DEFAULT GATE의 실제 판정.

여기서 지키는 계약:
  ① **깨끗하다** — 정산·규정문서·과목별 룰이 하나도 없고 ACTIVE 그래프는 게이트 하나뿐.
  ② **게이트가 실제로 판정한다** — 조립기가 항상 채우는 필드만 참조하므로
     정상 건은 강등 없이 `PASS`가 나온다. 이게 깨지면 전건이 IN_REVIEW로 고인다.
  ③ **정책값을 참조하지 않는다** — `policy.*`를 쓰면 별표 없는 신규 설치에서
     미해소 가드가 전건을 REVIEW로 떨어뜨린다.
"""
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from domain.cards.models import Card
from domain.policies import orchestrator
from domain.policies.dsl import extract_vars
from domain.policies.models import PolicyDoc, RuleGraph, RuleGraphStatus
from domain.settlements.models import Settlement
from domain.settlements.models import SettlementStatus as S
from domain.transactions.models import Receipt, Transaction
from domain.accounts.models import User


def _settlement(*, receipt=True, purpose="거래처 접대", industry="한식", ai_suggested=False):
    """게이트가 보는 네 가지 사실을 조합해 정산 1건을 만든다."""
    card = Card.objects.filter(card_type="PERSONAL").first()
    tx = Transaction.objects.create(
        card=card, merchant="강남한식당", amount=Decimal("120000"), ts=timezone.now(),
    )
    if receipt:
        Receipt.objects.create(matched_tx=tx, status="MATCHED", file_ref="r.jpg")
    return Settlement.objects.create(
        transaction=tx, category="접대", status=S.SUBMITTED,
        purpose=purpose, merchant_industry=industry, ai_suggested=ai_suggested,
    )


class SeedCleanStateTests(TestCase):
    def setUp(self):
        call_command("seed_clean", verbosity=0)

    def test_only_the_default_gate_is_active(self):
        graphs = list(RuleGraph.objects.filter(status=RuleGraphStatus.ACTIVE))
        self.assertEqual(len(graphs), 1)
        self.assertEqual(graphs[0].scope, "GLOBAL")
        # 과목별 룰은 사전 탑재하지 않는다 — 고객 규정 문서에서 생성한다(CLAUDE.md §2).
        self.assertFalse(RuleGraph.objects.exclude(scope="GLOBAL").exists())

    def test_no_demo_transaction_data(self):
        self.assertFalse(Settlement.objects.exists())
        self.assertFalse(Transaction.objects.exists())
        self.assertFalse(PolicyDoc.objects.exists())

    def test_login_accounts_match_the_demo_seed(self):
        """시드를 갈아끼울 때마다 로그인 정보가 바뀌면 시연 중에 헤맨다."""
        for username in ("kim", "lead", "acc", "acclead", "exec"):
            self.assertTrue(User.objects.filter(username=username).exists(), username)
        self.assertTrue(self.client.login(username="acc", password="pass1234"))

    def test_cards_exist_so_registration_is_possible(self):
        """카드가 없으면 신규 지출 등록에서 카드를 못 골라 시연이 막힌다."""
        self.assertTrue(Card.objects.exists())

    def test_rerun_is_idempotent(self):
        call_command("seed_clean", verbosity=0)
        self.assertEqual(RuleGraph.objects.filter(status=RuleGraphStatus.ACTIVE).count(), 1)
        self.assertEqual(User.objects.filter(username="kim").count(), 1)


class DefaultGateJudgementTests(TestCase):
    """게이트가 **실제 판정 경로**(orchestrator)에서 의도대로 도는지."""

    def setUp(self):
        call_command("seed_clean", verbosity=0)

    def test_complete_record_passes_without_demotion(self):
        """이게 깨지면 정상 건까지 전부 IN_REVIEW로 고인다 — 게이트의 존재 이유가 사라진다."""
        result = orchestrator.judge(_settlement(), record=False)
        self.assertEqual(result.decision, "PASS")
        # 미해소 강등이 없어야 한다(참조 필드가 전부 채워졌다는 뜻).
        self.assertFalse([f for f in result.flags if f.startswith("UNRESOLVED")], result.flags)

    def test_missing_receipt_returns(self):
        result = orchestrator.judge(_settlement(receipt=False), record=False)
        self.assertEqual(result.decision, "RETURN")
        self.assertIn("MISSING_RECEIPT", result.flags)

    def test_missing_purpose_returns(self):
        result = orchestrator.judge(_settlement(purpose=""), record=False)
        self.assertEqual(result.decision, "RETURN")
        self.assertIn("MISSING_PURPOSE", result.flags)

    def test_unresolved_merchant_goes_to_review(self):
        result = orchestrator.judge(_settlement(industry=""), record=False)
        self.assertEqual(result.decision, "REVIEW")
        self.assertIn("MERCHANT_UNRESOLVED", result.flags)

    def test_low_confidence_category_goes_to_review(self):
        result = orchestrator.judge(_settlement(ai_suggested=True), record=False)
        self.assertEqual(result.decision, "REVIEW")
        self.assertIn("LOW_CATEGORY_CONFIDENCE", result.flags)

    def test_gate_does_not_reference_company_policy(self):
        """`policy.*`를 참조하면 별표가 없는 신규 설치에서 전건이 REVIEW로 강등된다."""
        gate = RuleGraph.objects.get(scope="GLOBAL", status=RuleGraphStatus.ACTIVE)
        referenced = set()
        for node in gate.nodes.all():
            referenced |= extract_vars(node.condition)
        self.assertFalse([p for p in referenced if p.startswith("policy.")], referenced)

    def test_gate_pass_leaves_scope_graph_absent_flag(self):
        """과목별 룰이 없는 게 정상 상태다 — 그 사실이 판정 근거에 남아야 한다."""
        result = orchestrator.judge(_settlement(), record=False)
        self.assertIn(orchestrator.NO_SCOPE_GRAPH_FLAG, result.flags)
