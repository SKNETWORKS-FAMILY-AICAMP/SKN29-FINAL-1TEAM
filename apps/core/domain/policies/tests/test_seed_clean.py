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
                amount="120000", category="접대", card_type="PERSONAL", actual_user_recorded=None):
    """게이트가 보는 사실을 조합해 정산 1건을 만든다.

    `actual_user_recorded`는 **팀·공용 카드에서만** 판정에 들어간다(개인카드는 소유자가 곧
    사용자라 조립기가 `True`로 접는다 — `context_builder.collect_from_settlement`).
    """
    card = Card.objects.filter(card_type=card_type).first()
    tx = Transaction.objects.create(
        card=card, merchant="강남한식당", amount=Decimal(amount), ts=timezone.now(),
    )
    if receipt:
        Receipt.objects.create(matched_tx=tx, status="MATCHED", file_ref="r.jpg")
    return Settlement.objects.create(
        transaction=tx, category=category, status=S.SUBMITTED,
        purpose=purpose, merchant_industry=industry, ai_suggested=ai_suggested,
        actual_user_recorded=actual_user_recorded,
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

    # ── 자동 통과(PASS)는 화이트리스트 ─────────────────────────────────

    def test_완결된_소액_건만_자동_통과한다(self):
        """증빙·목적·분류가 있고 업종을 확인했으며 소액일 때만 승인 대기로 직행한다."""
        result = orchestrator.judge(_settlement(), record=False)
        self.assertEqual(result.decision, "PASS")
        self.assertFalse([f for f in result.flags if f.startswith("UNRESOLVED")], result.flags)

    def test_요건이_하나라도_빠지면_검토로_간다(self):
        """**기본값은 검토다.** 자동 통과는 전부 만족했을 때만 나온다."""
        cases = {
            "증빙 없음": _settlement(receipt=False),
            "목적 없음": _settlement(purpose=""),
            "분류 없음": _settlement(category=""),
            "업종 미확정": _settlement(industry=""),
            "위험 업종": _settlement(industry="사행성업종"),
            "고액": _settlement(amount="300000"),
        }
        for label, settlement in cases.items():
            with self.subTest(label):
                self.assertEqual(orchestrator.judge(settlement, record=False).decision, "REVIEW")

    # ── 검토로 갈 때 **사유가 붙어서** 간다 ────────────────────────────

    def test_해당하는_사유가_전부_붙는다(self):
        """사유마다 단말로 끊으면 첫 번째 하나만 남아 검토자가 전체를 못 본다."""
        result = orchestrator.judge(
            _settlement(receipt=False, purpose="", category="", industry="사행성업종",
                        amount="5000000"),
            record=False,
        )
        self.assertEqual(result.decision, "REVIEW")
        for flag in ("PROHIBITED_MERCHANT", "EVIDENCE_MISSING", "PURPOSE_UNCLEAR",
                     "CATEGORY_MISSING", "HIGH_AMOUNT"):
            self.assertIn(flag, result.flags)

    def test_위험업종_사유(self):
        result = orchestrator.judge(_settlement(industry="사행성업종"), record=False)
        self.assertIn("PROHIBITED_MERCHANT", result.flags)

    def test_규정_원문_표기도_같은_사유로_접힌다(self):
        """`유흥주점` 같은 원문 표기도 정본 어휘로 접혀 같은 룰에 걸린다."""
        result = orchestrator.judge(_settlement(industry="유흥주점"), record=False)
        self.assertIn("PROHIBITED_MERCHANT", result.flags)

    def test_업종_미확정은_전용_사유로_표시된다(self):
        """`UNRESOLVED_FACT`가 아니라 `MERCHANT_UNRESOLVED`여야 한다 — 분기로 우회한 이유."""
        result = orchestrator.judge(_settlement(industry=""), record=False)
        self.assertIn("MERCHANT_UNRESOLVED", result.flags)
        self.assertNotIn("UNRESOLVED_FACT:merchant.merchant_type", result.flags)

    def test_고액_사유(self):
        result = orchestrator.judge(_settlement(amount="1000000"), record=False)
        self.assertIn("HIGH_AMOUNT", result.flags)

    # ── 팀·공용 카드 실사용자 (2026-08-23 정합 점검에서 나온 결함 2건의 회귀) ──────

    def test_실사용자_미등록은_자동_통과하지_않는다(self):
        """**실측 결함**: 사유(`ACTUAL_USER_REQUIRED`)가 붙은 채로 `PASS`가 나왔다.

        미해소 가드에 맡겨 뒀던 요건이라 `None`(모름)은 막혔지만 **명시적 `False`**
        (기록하지 않았다고 적힌 건)는 아무도 안 봤다 — 누가 썼는지 모르는 공용카드 결제가
        자동으로 승인 대기까지 갔다. 자동 통과 화이트리스트에 명시해 막는다.
        """
        result = orchestrator.judge(
            _settlement(card_type="SHARED", actual_user_recorded=False), record=False)
        self.assertEqual(result.decision, "REVIEW")
        self.assertIn("ACTUAL_USER_REQUIRED", result.flags)

    def test_실사용자_모름은_전용_사유로_표시된다(self):
        """**실측 결함**: `UNRESOLVED_FACT:card.actual_user_recorded` + confidence 0이 나왔다.

        업종 미확정과 같은 처리를 해야 한다 — 검토자에게 "판정 정보 부족"보다
        "실사용자 미등록"이 훨씬 쓸모 있다. `is_null` 분기로 우회해 가드를 피한다.
        """
        result = orchestrator.judge(
            _settlement(card_type="SHARED", actual_user_recorded=None), record=False)
        self.assertEqual(result.decision, "REVIEW")
        self.assertIn("ACTUAL_USER_REQUIRED", result.flags)
        self.assertNotIn("UNRESOLVED_FACT:card.actual_user_recorded", result.flags)
        # 미해소 강등이면 엔진이 confidence를 0으로 떨어뜨린다 — 그 흔적이 없어야 한다.
        self.assertEqual([r.result.confidence for r in result.runs], [1.0])

    def test_실사용자_기록된_공용카드는_통과한다(self):
        """막는 게 목적이 아니다 — 기록이 있으면 개인카드와 똑같이 자동 통과해야 한다."""
        result = orchestrator.judge(
            _settlement(card_type="SHARED", actual_user_recorded=True), record=False)
        self.assertEqual(result.decision, "PASS")

    def test_개인카드는_실사용자를_묻지_않는다(self):
        """소유자가 곧 사용자라 조립기가 `True`로 접는다 — 여기서 물으면 전건이 걸린다."""
        result = orchestrator.judge(
            _settlement(card_type="PERSONAL", actual_user_recorded=None), record=False)
        self.assertEqual(result.decision, "PASS")
        self.assertNotIn("ACTUAL_USER_REQUIRED", result.flags)

    # ── 결정 규약 ─────────────────────────────────────────────────────

    def test_게이트는_반려나_보완요청을_내지_않는다(self):
        """`RETURN`·`REJECT`는 회사가 무엇을 요구하는지 정해진 뒤의 결정이다."""
        cases = [
            _settlement(industry="사행성업종"),
            _settlement(receipt=False),
            _settlement(category=""),
            _settlement(purpose=""),
            _settlement(amount="9000000"),
            _settlement(),
        ]
        for settlement in cases:
            result = orchestrator.judge(settlement, record=False)
            self.assertIn(result.decision, {"PASS", "REVIEW"}, result.flags)

    def test_통과한_건에는_사유가_붙지_않는다(self):
        """사유 없이 통과해야 검토자가 「왜 통과했지」를 되묻지 않는다."""
        result = orchestrator.judge(_settlement(), record=False)
        rule_flags = [f for f in result.flags if not f.startswith("NO_SCOPE")]
        self.assertEqual(rule_flags, [], result.flags)

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
