"""`seed_clean` 회귀 — 시연용 초기 상태와 DEFAULT GATE의 실제 판정.

여기서 지키는 계약:
  ① **깨끗하다** — 정산·규정문서·과목별 룰이 하나도 없고 ACTIVE 그래프는 게이트 하나뿐.
  ② **게이트가 실제로 판정한다** — 조립기가 항상 채우는 필드만 참조하므로
     정상 건은 강등 없이 `PASS`가 나온다. 이게 깨지면 전건이 IN_REVIEW로 고인다.
  ③ **정책값을 참조하지 않는다** — `policy.*`를 쓰면 별표 없는 신규 설치에서
     미해소 가드가 전건을 REVIEW로 떨어뜨린다.
  ④ **막지 않고 사람에게 넘긴다** — 걸린 건은 전부 `REVIEW`다. `RETURN`(지출자에게
     되돌려보냄)은 회사가 무엇을 요구하는지 정해지기 전에 내릴 결정이 아니다.
  ⑤ **초기 도입은 유연하게** — 소액 증빙 누락·업종 미확정처럼 걸 이유가 분명하지 않은
     건은 통과시킨다. 전건이 걸리면 게이트가 신호를 잃는다.
"""
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from domain.cards.models import Card
from domain.policies import orchestrator
from domain.policies.dsl import extract_vars
from domain.policies.models import PolicyDoc, RuleGraph, RuleGraphStatus
from domain.settlements.models import Category, Settlement, TeamBudget
from domain.settlements.models import SettlementStatus as S
from domain.transactions.models import Receipt, Transaction
from domain.accounts.models import User


def _settlement(*, receipt=True, purpose="거래처 접대", industry="한식", ai_suggested=False,
                amount="120000", category="접대"):
    """게이트가 보는 사실을 조합해 정산 1건을 만든다."""
    card = Card.objects.filter(card_type="PERSONAL").first()
    tx = Transaction.objects.create(
        card=card, merchant="강남한식당", amount=Decimal(amount), ts=timezone.now(),
    )
    if receipt:
        Receipt.objects.create(matched_tx=tx, status="MATCHED", file_ref="r.jpg")
    return Settlement.objects.create(
        transaction=tx, category=category, status=S.SUBMITTED,
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

    def test_team_budgets_exist_for_this_month(self):
        """예산 화면이 빈 껍데기가 아니려면 한도 행이 있어야 한다(사용액은 집계라 0이 정상)."""
        month = timezone.localdate().strftime("%Y-%m")
        rows = TeamBudget.objects.filter(year_month=month)
        self.assertTrue(rows.exists())
        # 팀마다 6개 과목 + 총액 1행.
        for team_id in rows.values_list("team_id", flat=True).distinct():
            per_team = rows.filter(team_id=team_id)
            self.assertEqual(per_team.count(), len(Category.values) + 1)

    def test_team_total_equals_sum_of_categories(self):
        """불변식 ① — 총한도 != 과목 한도 합이면 대시보드가 원인 없이 어긋난다."""
        month = timezone.localdate().strftime("%Y-%m")
        for team_id in TeamBudget.objects.values_list("team_id", flat=True).distinct():
            rows = TeamBudget.objects.filter(team_id=team_id, year_month=month)
            total = rows.get(category="").limit_amount
            self.assertEqual(total, sum(r.limit_amount for r in rows.exclude(category="")))

    def test_every_category_has_a_budget_row(self):
        """불변식 ② — 빠진 과목의 지출은 총액엔 잡히는데 항목 카드엔 안 보인다."""
        month = timezone.localdate().strftime("%Y-%m")
        for team_id in TeamBudget.objects.values_list("team_id", flat=True).distinct():
            have = set(TeamBudget.objects.filter(team_id=team_id, year_month=month)
                       .exclude(category="").values_list("category", flat=True))
            self.assertEqual(have, set(Category.values))

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

    # ── 거는 것 4가지 (전부 REVIEW) ────────────────────────────────────

    def test_legal_risk_merchant_goes_to_review(self):
        """법령·세법 위험 업종은 어느 회사에나 해당하는 축이라 기본값에 둔다."""
        result = orchestrator.judge(_settlement(industry="사행성업종"), record=False)
        self.assertEqual(result.decision, "REVIEW")
        self.assertIn("PROHIBITED_MERCHANT", result.flags)

    def test_legal_risk_merchant_accepts_regulation_wording(self):
        """규정 원문 표기(`유흥주점`)도 정본 어휘로 접혀 같은 룰에 걸린다."""
        result = orchestrator.judge(_settlement(industry="유흥주점"), record=False)
        self.assertEqual(result.decision, "REVIEW")
        self.assertIn("PROHIBITED_MERCHANT", result.flags)

    def test_high_amount_without_receipt_goes_to_review(self):
        result = orchestrator.judge(
            _settlement(receipt=False, amount="1000000"), record=False)
        self.assertEqual(result.decision, "REVIEW")
        self.assertIn("EVIDENCE_MISSING", result.flags)

    def test_missing_category_goes_to_review(self):
        result = orchestrator.judge(_settlement(category=""), record=False)
        self.assertEqual(result.decision, "REVIEW")
        self.assertIn("CATEGORY_MISSING", result.flags)

    def test_missing_purpose_goes_to_review(self):
        result = orchestrator.judge(_settlement(purpose=""), record=False)
        self.assertEqual(result.decision, "REVIEW")
        self.assertIn("PURPOSE_UNCLEAR", result.flags)

    # ── 통과시키는 것 (초기 도입 유연성) ───────────────────────────────

    def test_small_amount_without_receipt_passes(self):
        """소액 증빙 누락까지 잡으면 초기 도입에서 전건이 검토로 몰린다."""
        result = orchestrator.judge(_settlement(receipt=False, amount="9000"), record=False)
        self.assertEqual(result.decision, "PASS")
        self.assertNotIn("EVIDENCE_MISSING", result.flags)

    def test_unresolved_merchant_passes_without_demotion(self):
        """**핵심 회귀** — 업종 미확정 건이 금지업종 노드를 지나면 미해소 가드가 강등한다.

        신규 설치엔 가맹점 캐시가 비어 있어 그게 대다수다. 분기(`n_industry_known`)로
        우회하지 않으면 게이트가 전건을 붙잡는다.
        """
        result = orchestrator.judge(_settlement(industry=""), record=False)
        self.assertEqual(result.decision, "PASS")
        self.assertFalse([f for f in result.flags if f.startswith("UNRESOLVED")], result.flags)

    def test_ai_suggested_category_passes(self):
        """AI 추천 분류는 그 자체로 걸 이유가 아니다 — 분류가 비어 있을 때만 건다."""
        result = orchestrator.judge(_settlement(ai_suggested=True), record=False)
        self.assertEqual(result.decision, "PASS")

    # ── 결정 규약 ─────────────────────────────────────────────────────

    def test_gate_never_returns_to_the_spender(self):
        """`RETURN`은 지출자에게 일을 되돌려보내는 결정이다 — 기본 게이트는 쓰지 않는다."""
        cases = [
            _settlement(industry="사행성업종"),
            _settlement(receipt=False, amount="2000000"),
            _settlement(category=""),
            _settlement(purpose=""),
        ]
        for settlement in cases:
            result = orchestrator.judge(settlement, record=False)
            self.assertNotIn(result.decision, {"RETURN", "REJECT"}, result.flags)

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
