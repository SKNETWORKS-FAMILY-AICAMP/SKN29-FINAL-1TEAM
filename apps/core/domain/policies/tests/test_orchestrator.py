"""룰 판정 동작 회귀 테스트 — 그래프 선택(FR-RA-10) · 상태 전이(기술명세서 §4.2(c)).

여기서 고정하는 계약은 넷이다:
  ① **게이트가 먼저다.** GLOBAL이 통과가 아니면 과목별 그래프는 아예 돌지 않는다.
  ② **규칙이 없으면 통과가 아니다.** ACTIVE 그래프가 없으면 REVIEW(사람에게).
  ③ **엔진은 최종반려를 만들지 않는다.** 노드 decision이 REJECT여도 상태는 RETURNED.
  ④ **판정 근거가 남는다.** 그래프당 `rule_hits` 한 행 + EvalContext 스냅샷.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from domain.cards.models import Card
from domain.policies import orchestrator
from domain.policies.models import RuleGraph, RuleGraphStatus, RuleHit, RuleNode, RuleRouting
from domain.settlements.models import Settlement
from domain.settlements.models import SettlementStatus as S
from domain.settlements.services import judge, submit
from domain.transactions.models import Transaction


def make_graph(scope, name, *, node_key, condition, decision, flag="", status=RuleGraphStatus.ACTIVE):
    """단일 노드 그래프 — 판정 결과가 오직 그 노드에서 나오게 해 선택 로직만 시험한다."""
    graph = RuleGraph.objects.create(
        name=name, scope=scope, status=status, version=1, entry_node_key=node_key,
    )
    RuleNode.objects.create(
        graph=graph, node_key=node_key, condition=condition,
        action={"decision": decision, "flag": flag, "title": name},
    )
    RuleRouting.objects.create(graph=graph, from_node_key=node_key, on_result="MATCH", to_node_key="")
    return graph


class OrchestratorBase(TestCase):
    def setUp(self):
        card = Card.objects.create(name="법인카드", card_type="SHARED")
        self.tx = Transaction.objects.create(
            card=card, merchant="강남한식당", amount=Decimal("452000"), ts=timezone.now(),
        )
        self.settlement = Settlement.objects.create(
            transaction=self.tx, category="접대", status=S.SUBMITTED, purpose="거래처 접대",
        )


class GraphSelectionTests(OrchestratorBase):
    def test_no_active_graph_is_review_not_pass(self):
        """검사할 규칙이 없는 것과 검사해보니 문제없는 것은 다르다."""
        result = orchestrator.judge(self.settlement)
        self.assertEqual(result.decision, "REVIEW")
        self.assertIn(orchestrator.NO_GRAPH_FLAG, result.flags)
        self.assertEqual(result.runs, [])

    def test_gate_blocks_before_scope_graph(self):
        """게이트가 통과가 아니면 과목별 그래프는 돌지 않는다 (FR-RA-10)."""
        make_graph("GLOBAL", "정산 1차 게이트", node_key="n_gate", condition=True,
                   decision="REVIEW", flag="GATE_STOP")
        make_graph("접대", "접대 세부", node_key="n_ent", condition=True, decision="PASS")

        result = orchestrator.judge(self.settlement)
        self.assertEqual(result.decision, "REVIEW")
        self.assertIn("GATE_STOP", result.flags)
        self.assertEqual([run.scope for run in result.runs], ["GLOBAL"])

    def test_gate_pass_continues_to_scope_graph(self):
        make_graph("GLOBAL", "정산 1차 게이트", node_key="n_gate", condition=True, decision="PASS")
        make_graph("접대", "접대 세부", node_key="n_ent", condition=True,
                   decision="RETURN", flag="FIELDS_MISSING")

        result = orchestrator.judge(self.settlement)
        # 최종 결정은 마지막으로 돌린 과목 그래프의 것.
        self.assertEqual(result.decision, "RETURN")
        self.assertEqual([run.scope for run in result.runs], ["GLOBAL", "접대"])
        self.assertIn("FIELDS_MISSING", result.flags)
        # 경로는 어느 그래프의 노드였는지 알 수 있게 스코프로 한정된다.
        self.assertEqual(result.path, ["GLOBAL:n_gate", "접대:n_ent"])

    def test_scope_graph_alone_is_used_when_no_gate(self):
        make_graph("접대", "접대 세부", node_key="n_ent", condition=True, decision="PASS")
        result = orchestrator.judge(self.settlement)
        self.assertEqual(result.decision, "PASS")
        self.assertEqual([run.scope for run in result.runs], ["접대"])

    def test_gate_pass_without_scope_graph_keeps_pass_but_flags_it(self):
        make_graph("GLOBAL", "정산 1차 게이트", node_key="n_gate", condition=True, decision="PASS")
        result = orchestrator.judge(self.settlement)
        self.assertEqual(result.decision, "PASS")
        self.assertIn(orchestrator.NO_SCOPE_GRAPH_FLAG, result.flags)

    def test_draft_graph_is_not_used(self):
        """승인되지 않은 초안이 실판정에 끼어들면 안 된다."""
        make_graph("접대", "접대 초안", node_key="n_ent", condition=True, decision="PASS",
                   status=RuleGraphStatus.DRAFT)
        result = orchestrator.judge(self.settlement)
        self.assertEqual(result.decision, "REVIEW")
        self.assertIn(orchestrator.NO_GRAPH_FLAG, result.flags)

    def test_scope_falls_back_to_ai_category(self):
        self.settlement.category = ""
        self.settlement.ai_category = "접대"
        self.settlement.save(update_fields=["category", "ai_category"])
        make_graph("접대", "접대 세부", node_key="n_ent", condition=True, decision="PASS")
        self.assertEqual(orchestrator.judge(self.settlement).decision, "PASS")

    def test_regulation_scope_name_is_normalized(self):
        """회식 그래프는 식대 scope에 편성된다 — 회식 정산도 그 그래프를 타야 한다."""
        self.settlement.category = "식대"
        self.settlement.save(update_fields=["category"])
        make_graph("식대", "식대·회식 세부", node_key="n_meal", condition=True, decision="REVIEW")
        result = orchestrator.judge(self.settlement)
        self.assertEqual(result.scope, "식대")
        self.assertEqual(result.decision, "REVIEW")


class RuleHitRecordingTests(OrchestratorBase):
    def test_one_hit_per_graph_with_snapshot(self):
        make_graph("GLOBAL", "게이트", node_key="n_gate", condition=True, decision="PASS")
        make_graph("접대", "접대 세부", node_key="n_ent", condition=True, decision="PASS")

        orchestrator.judge(self.settlement)
        hits = list(RuleHit.objects.filter(settlement=self.settlement).order_by("id"))
        self.assertEqual(len(hits), 2)
        self.assertEqual([hit.graph.scope for hit in hits], ["GLOBAL", "접대"])
        for hit in hits:
            # 그때의 사실이 남아야 판정을 다시 돌려볼 수 있다.
            self.assertTrue(hit.eval_context)
            self.assertEqual(hit.eval_context_schema_version, 5)
            self.assertEqual(hit.transaction_id, self.tx.pk)

    def test_hit_is_recorded_even_without_graphs(self):
        """규칙이 없었다는 사실과 그때의 EvalContext도 감사 대상이다."""
        orchestrator.judge(self.settlement)
        hit = RuleHit.objects.get(settlement=self.settlement)
        self.assertIsNone(hit.graph_id)
        self.assertEqual(hit.decision, "REVIEW")
        self.assertTrue(hit.eval_context)

    def test_record_false_leaves_no_trace(self):
        make_graph("접대", "접대 세부", node_key="n_ent", condition=True, decision="PASS")
        orchestrator.judge(self.settlement, record=False)
        self.assertFalse(RuleHit.objects.filter(settlement=self.settlement).exists())


class JudgeStateTransitionTests(OrchestratorBase):
    def _judge_with(self, decision):
        make_graph("접대", "접대 세부", node_key="n_ent", condition=True,
                   decision=decision, flag="X")
        judge(self.settlement)
        self.settlement.refresh_from_db()
        return self.settlement.status

    def test_pass_goes_to_pending_confirm(self):
        # 확신 통과도 사람 확정 없이는 CONFIRMED가 아니다 (FR-RA-02·FR-ST-03).
        self.assertEqual(self._judge_with("PASS"), S.PENDING_CONFIRM)

    def test_return_goes_to_returned(self):
        self.assertEqual(self._judge_with("RETURN"), S.RETURNED)

    def test_reject_decision_does_not_terminate_the_settlement(self):
        """엔진의 REJECT는 보완요청이다 — 최종반려(재제출 불가)는 사람만 내린다."""
        self.assertEqual(self._judge_with("REJECT"), S.RETURNED)

    def test_review_goes_to_in_review(self):
        self.assertEqual(self._judge_with("REVIEW"), S.IN_REVIEW)

    def test_no_graph_goes_to_in_review(self):
        judge(self.settlement)
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, S.IN_REVIEW)

    def test_rpa_judged_is_recorded_in_the_audit_trail(self):
        """RPA_JUDGED를 건너뛰면 '언제 룰이 봤는지'가 이력에서 사라진다."""
        make_graph("접대", "접대 세부", node_key="n_ent", condition=True, decision="PASS")
        judge(self.settlement)
        states = list(self.settlement.events.order_by("id").values_list("to_state", flat=True))
        self.assertEqual(states, [S.RPA_JUDGED, S.PENDING_CONFIRM])

    def test_transition_reason_carries_the_judgement(self):
        make_graph("접대", "접대 세부", node_key="n_ent", condition=True,
                   decision="RETURN", flag="FIELDS_MISSING")
        judge(self.settlement)
        reason = self.settlement.events.order_by("-id").first().reason
        self.assertIn("RETURN", reason)
        self.assertIn("접대 세부 v1", reason)
        self.assertIn("FIELDS_MISSING", reason)

    def test_resubmission_rejudges_and_keeps_both_hits(self):
        """보완 후 재제출하면 판정이 다시 돈다 — 이력은 덮이지 않고 쌓인다."""
        make_graph("접대", "접대 세부", node_key="n_ent", condition=True, decision="RETURN")
        judge(self.settlement)
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, S.RETURNED)

        submit(self.settlement)
        judge(self.settlement)
        self.settlement.refresh_from_db()
        self.assertEqual(RuleHit.objects.filter(settlement=self.settlement).count(), 2)


class SubmitTriggersJudgementTests(OrchestratorBase):
    """제출은 룰 판정으로 이어져야 한다 — 아니면 정산이 SUBMITTED에 고인다."""

    def setUp(self):
        super().setUp()
        self.settlement.status = S.TEAM_COLLECTING
        self.settlement.save(update_fields=["status"])
        make_graph("접대", "접대 세부", node_key="n_ent", condition=True, decision="PASS")

    def test_submit_endpoint_judges_and_reports_result(self):
        resp = self.client.post(
            "/api/settlements/submit/", {"ids": [self.settlement.pk]}, content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["submitted"], [self.settlement.pk])
        self.assertEqual(resp.data["judged"][str(self.settlement.pk)]["decision"], "PASS")
        self.assertEqual(resp.data["judged"][str(self.settlement.pk)]["status"], S.PENDING_CONFIRM)
        self.assertEqual(resp.data["judgeFailed"], {})

        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, S.PENDING_CONFIRM)

    def test_judge_endpoint_returns_the_reasoning(self):
        submit(self.settlement)
        resp = self.client.post(f"/api/settlements/{self.settlement.pk}/judge/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["ruleResult"]["decision"], "PASS")
        self.assertEqual(resp.data["ruleResult"]["graphs"][0]["name"], "접대 세부")
