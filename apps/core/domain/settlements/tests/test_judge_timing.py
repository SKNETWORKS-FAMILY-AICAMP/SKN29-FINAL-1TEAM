"""룰 판정 시점 회귀 — **팀 취합에 올라온 시점에 한 번**.

고정하는 계약:
  ① 판정은 `raise_to_team`에서 돈다 — 팀장이 판정 결과를 보고 취합해야 한다.
     예전엔 회계 제출 뒤에야 돌아서, 팀 화면은 `amount >= 300000` 같은 프론트 상수로
     이상 여부를 흉내내고 있었다(어느 규정에서도 오지 않은 숫자).
  ② 판정은 **상태를 바꾸지 않는다** — 팀에 올라온 건은 팀장이 올려야 넘어간다.
  ③ 제출은 기록된 판정을 **재사용**한다 — 다시 돌리면 `rule_hits`가 회차별로 쌓여
     검토 화면이 어느 게 최신 근거인지 잃는다.
  ④ 회계 보완요청 재제출(`RETURNED → SUBMITTED`)만 재판정한다 — 팀 단계를 거치지
     않았고 사실이 바뀐 뒤라 옛 판정을 쓰면 안 된다.
  ⑤ 판정 실패가 '올림'을 되돌리지 않는다 — 되돌리면 개인이 팀에 올릴 수조차 없다.
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from domain.accounts.models import Role, Team, User
from domain.cards.models import Card
from domain.policies.models import (
    RuleGraph,
    RuleGraphStatus,
    RuleHit,
    RuleNode,
    RuleRouting,
)
from domain.policies.scope import GLOBAL
from domain.settlements import services
from domain.settlements.models import Settlement
from domain.settlements.models import SettlementStatus as S
from domain.transactions.models import Transaction


def _graph(scope, decision, *, name=None, flag=""):
    graph = RuleGraph.objects.create(
        name=name or f"{scope} 그래프", scope=scope, status=RuleGraphStatus.ACTIVE,
        version=1, entry_node_key="n1",
    )
    action = {"decision": decision, "title": "t"}
    if flag:
        action["flag"] = flag
    RuleNode.objects.create(graph=graph, node_key="n1", condition=True, action=action)
    RuleRouting.objects.create(graph=graph, from_node_key="n1", on_result="MATCH", to_node_key="")
    return graph


class JudgeOnRaiseTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="영업1팀")
        self.user = User.objects.create_user("kim", password="pw", role=Role.EMPLOYEE, team=self.team)
        card = Card.objects.create(name="법인카드", card_type="SHARED")
        tx = Transaction.objects.create(
            card=card, merchant="강남한식당", amount=Decimal("452000"), ts=timezone.now(),
        )
        self.settlement = Settlement.objects.create(
            transaction=tx, category="접대", status=S.DRAFT, purpose="접대", team=self.team,
        )

    def test_raise_runs_the_engine(self):
        _graph(GLOBAL, "PASS")
        services.raise_to_team(self.settlement, self.user)
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.rule_decision, "PASS")
        self.assertIsNotNone(self.settlement.rule_judged_at)
        self.assertTrue(RuleHit.objects.filter(settlement=self.settlement).exists())

    def test_raise_does_not_transition_past_team(self):
        """판정이 상태를 옮기면 팀장이 보기도 전에 회계로 넘어간다."""
        _graph(GLOBAL, "REJECT")
        services.raise_to_team(self.settlement, self.user)
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, S.TEAM_COLLECTING)

    def test_flags_are_recorded_for_the_team_screen(self):
        """팀 화면의 "판정 사유"가 이 값이다 — 없으면 왜 걸렸는지 알 수 없다."""
        _graph(GLOBAL, "RETURN", flag="MISSING_RECEIPT")
        services.raise_to_team(self.settlement, self.user)
        self.settlement.refresh_from_db()
        self.assertIn("MISSING_RECEIPT", self.settlement.rule_flags)

    def test_judgement_failure_does_not_undo_the_raise(self):
        with patch("domain.policies.orchestrator.judge", side_effect=RuntimeError("boom")):
            services.raise_to_team(self.settlement, self.user)
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, S.TEAM_COLLECTING)
        self.assertEqual(self.settlement.rule_decision, "")


class SubmitReusesJudgementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("kim", password="pw", role=Role.EMPLOYEE)
        card = Card.objects.create(name="법인카드", card_type="SHARED")
        tx = Transaction.objects.create(
            card=card, merchant="강남한식당", amount=Decimal("452000"), ts=timezone.now(),
        )
        self.settlement = Settlement.objects.create(
            transaction=tx, category="접대", status=S.DRAFT, purpose="접대",
        )

    def test_submit_does_not_rerun_the_engine(self):
        """엔진을 두 번 돌리면 `rule_hits`가 회차별로 쌓여 최신 근거를 잃는다."""
        _graph(GLOBAL, "PASS")
        services.raise_to_team(self.settlement, self.user)
        hits_after_raise = RuleHit.objects.filter(settlement=self.settlement).count()

        services.submit(self.settlement, self.user)
        services.judge(self.settlement, self.user, reuse_recorded=True)

        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, S.PENDING_CONFIRM)   # PASS → 승인대기
        self.assertEqual(RuleHit.objects.filter(settlement=self.settlement).count(), hits_after_raise)

    def test_recorded_decision_drives_the_state(self):
        _graph(GLOBAL, "REVIEW")
        services.raise_to_team(self.settlement, self.user)
        services.submit(self.settlement, self.user)
        with patch("domain.settlements.risk_review.schedule"):
            services.judge(self.settlement, self.user, reuse_recorded=True)
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, S.IN_REVIEW)

    def test_resubmission_rejudges(self):
        """회계 보완요청 후 재제출은 팀 단계를 안 거친다 — 옛 판정을 쓰면 고친 게 반영 안 된다."""
        graph = _graph(GLOBAL, "RETURN")
        services.raise_to_team(self.settlement, self.user)
        services.submit(self.settlement, self.user)
        services.judge(self.settlement, self.user, reuse_recorded=True)
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, S.RETURNED)

        # 규칙이 바뀌어 이제는 통과한다 — 재제출 시 그 변화가 반영돼야 한다.
        RuleNode.objects.filter(graph=graph).update(action={"decision": "PASS", "title": "t"})
        services.submit(self.settlement, self.user)
        services.judge(self.settlement, self.user, reuse_recorded=False)
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, S.PENDING_CONFIRM)

    def test_missing_record_falls_back_to_running_the_engine(self):
        """팀 단계 판정이 실패했더라도 제출이 판정 없이 통과하면 안 된다."""
        _graph(GLOBAL, "PASS")
        self.settlement.status = S.TEAM_COLLECTING
        self.settlement.save(update_fields=["status"])   # raise를 거치지 않음 = 기록 없음
        services.submit(self.settlement, self.user)
        services.judge(self.settlement, self.user, reuse_recorded=True)
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.rule_decision, "PASS")
        self.assertEqual(self.settlement.status, S.PENDING_CONFIRM)
