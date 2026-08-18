"""Agent ↔ 프론트 연동 회귀 — 화면이 실제로 닿는 경로를 고정한다.

여기서 지키는 것:
  ① **Risk Review는 제출 경로에서도 돈다.** 예전에는 수동 `/judge/` 액션 안에만 호출이
     있어서, 제출이 판정을 자동으로 이어 돌리게 바뀐 뒤 정상 흐름에서 통째로 빠졌다.
  ② Risk Review는 `IN_REVIEW`로 끝난 건에만 붙고, **실패해도 판정을 되돌리지 않는다**.
  ③ 대화형 룰 수정(`/rules/{id}/converse/`)이 인가·입력검증을 거쳐 ai로 전달된다.
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from domain.accounts.models import Capability, Role, User
from domain.cards.models import Card
from domain.policies.models import RuleGraph, RuleGraphStatus, RuleNode, RuleRouting
from domain.risk.models import RiskReview
from domain.settlements.models import Settlement
from domain.settlements.models import SettlementStatus as S
from domain.transactions.models import Transaction

# FastAPI `/agent/risk-review` 응답 모양(1차 이상탐지 + 2차 RAG 검증).
AI_RESPONSE = {
    "stage1_anomaly": {"anomaly_score": 0.87, "contribs": [{"feature": "amount", "weight": 0.4}]},
    "stage2_rag_review": {
        "violation_verdict": "VIOLATION",
        "review_reasons": ["1인당 한도 초과"],
        "recommendation": "SUPPLEMENT",
        "citations": [{"doc": "회식_운영규정", "article": "제5조", "quote_summary": "1인당 5만원"}],
        "similar_cases": [{"case_id": "C-12", "outcome": "RETURN", "relevance": "유사 금액대"}],
    },
}


def _graph(scope, decision):
    graph = RuleGraph.objects.create(
        name=f"{scope} 그래프", scope=scope, status=RuleGraphStatus.ACTIVE,
        version=1, entry_node_key="n1",
    )
    RuleNode.objects.create(graph=graph, node_key="n1", condition=True,
                            action={"decision": decision, "title": "t"})
    RuleRouting.objects.create(graph=graph, from_node_key="n1", on_result="MATCH", to_node_key="")
    return graph


class RiskReviewTriggerTests(TestCase):
    """판정이 IN_REVIEW로 넘긴 건에 Risk Review Agent가 붙는가."""

    def setUp(self):
        card = Card.objects.create(name="법인카드", card_type="SHARED")
        tx = Transaction.objects.create(
            card=card, merchant="강남한식당", amount=Decimal("452000"), ts=timezone.now(),
        )
        self.settlement = Settlement.objects.create(
            transaction=tx, category="접대", status=S.TEAM_COLLECTING, purpose="접대",
        )
        self.client = APIClient()

    def _submit(self):
        return self.client.post(
            "/api/settlements/submit/", {"ids": [self.settlement.pk]}, format="json"
        )

    def test_submit_path_runs_risk_review(self):
        """제출 → 판정 → IN_REVIEW 경로에서도 Agent가 돈다(예전엔 여기서 빠졌다)."""
        _graph("접대", "REVIEW")
        with patch("domain.settlements.risk_review.httpx.post") as post:
            post.return_value.json.return_value = AI_RESPONSE
            post.return_value.raise_for_status.return_value = None
            with self.captureOnCommitCallbacks(execute=True):
                resp = self._submit()

        self.assertEqual(resp.status_code, 200)
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, S.IN_REVIEW)

        review = RiskReview.objects.get(settlement=self.settlement)
        self.assertEqual(review.anomaly_score, 0.87)
        # SUPPLEMENT는 우리 도메인에서 '보완요청'이다.
        self.assertEqual(review.ai_recommendation, "RETURN")
        self.assertEqual(review.stage2_verdict["violation_verdict"], "VIOLATION")
        # 인용·유사사례가 화면 계약(rag_refs)으로 접혀 들어간다.
        self.assertEqual(len(review.rag_refs), 2)

    def test_not_called_when_judgement_passes(self):
        """통과 건까지 Agent를 부르면 LLM 비용만 나간다."""
        _graph("접대", "PASS")
        with patch("domain.settlements.risk_review.httpx.post") as post:
            with self.captureOnCommitCallbacks(execute=True):
                self._submit()
        post.assert_not_called()
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, S.PENDING_CONFIRM)
        self.assertFalse(RiskReview.objects.filter(settlement=self.settlement).exists())

    def test_ai_failure_does_not_undo_the_judgement(self):
        """AI가 죽어도 검토자는 육안 검토를 계속할 수 있어야 한다."""
        _graph("접대", "REVIEW")
        with patch("domain.settlements.risk_review.httpx.post", side_effect=OSError("연결 실패")):
            with self.captureOnCommitCallbacks(execute=True):
                resp = self._submit()

        self.assertEqual(resp.status_code, 200)
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, S.IN_REVIEW)      # 전이는 유지
        self.assertFalse(RiskReview.objects.filter(settlement=self.settlement).exists())

    def test_manual_judge_endpoint_also_runs_it(self):
        """수동 재판정 경로도 같은 서비스를 지나므로 자동으로 붙는다."""
        _graph("접대", "REVIEW")
        Settlement.objects.filter(pk=self.settlement.pk).update(status=S.SUBMITTED)
        with patch("domain.settlements.risk_review.httpx.post") as post:
            post.return_value.json.return_value = AI_RESPONSE
            post.return_value.raise_for_status.return_value = None
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(f"/api/settlements/{self.settlement.pk}/judge/")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["ruleResult"]["decision"], "REVIEW")
        self.assertEqual(RiskReview.objects.filter(settlement=self.settlement).count(), 1)


class ReviewWorkspaceContractTests(TestCase):
    """검토 워크스페이스(S-03)가 Risk Review 결과를 실제로 받는가.

    구 `/api/risk-review-v0/*` 화면을 없애면서 그쪽에만 있던 **2차 판정
    (`violation_verdict`)** 을 본 계약으로 옮겼다. 권고(`aiRecommendation`)와 다른 축이라
    빠지면 `INSUFFICIENT_INFO`(판단 보류)가 "문제없음"으로 보인다.
    """

    def setUp(self):
        card = Card.objects.create(name="법인카드", card_type="SHARED")
        tx = Transaction.objects.create(
            card=card, merchant="강남한식당", amount=Decimal("452000"), ts=timezone.now(),
        )
        self.settlement = Settlement.objects.create(
            transaction=tx, category="접대", status=S.IN_REVIEW, purpose="접대",
        )
        User.objects.create_user("acc", password="pw", role=Role.ACCOUNTANT)
        self.client = APIClient()
        self.client.login(username="acc", password="pw")

    def test_detail_exposes_verdict_and_evidence(self):
        RiskReview.objects.create(
            settlement=self.settlement,
            anomaly_score=0.91,
            reasons=[{"feature": "amount", "weight": 0.4}],
            anomaly_reasons=["1인당 한도 초과"],
            rag_refs=[{"title": "1인당 5만원", "source": "회식_운영규정 제5조", "kind": "policy"}],
            ai_recommendation="RETURN",
            stage2_verdict={"violation_verdict": "VIOLATION", "recommendation": "SUPPLEMENT"},
        )
        resp = self.client.get(f"/api/settlements/{self.settlement.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["anomalyScore"], 0.91)
        self.assertEqual(resp.data["aiRecommendation"], "RETURN")
        self.assertEqual(resp.data["violationVerdict"], "VIOLATION")
        self.assertEqual(len(resp.data["ragRefs"]), 1)
        self.assertEqual(resp.data["anomalyReasons"], ["1인당 한도 초과"])

    def test_insufficient_info_is_not_collapsed_into_no_violation(self):
        """판단 보류는 '문제없음'이 아니다 — 담당자가 반드시 구분해서 봐야 한다."""
        RiskReview.objects.create(
            settlement=self.settlement, anomaly_score=0.4,
            ai_recommendation="APPROVE",
            stage2_verdict={"violation_verdict": "INSUFFICIENT_INFO"},
        )
        resp = self.client.get(f"/api/settlements/{self.settlement.pk}/")
        self.assertEqual(resp.data["violationVerdict"], "INSUFFICIENT_INFO")

    def test_no_risk_review_yet_returns_empty_verdict(self):
        """Agent가 아직 안 돈 건을 '위반 없음'으로 채우면 안 된다."""
        resp = self.client.get(f"/api/settlements/{self.settlement.pk}/")
        self.assertEqual(resp.data["violationVerdict"], "")

    def test_review_decision_goes_through_the_single_path(self):
        """검토 결정 경로는 `/settlements/{id}/review/` 하나다(구 v0 경로는 제거됨)."""
        resp = self.client.post(
            f"/api/settlements/{self.settlement.pk}/review/",
            {"decision": "RETURN", "reason": "참석자 명단 필요"}, format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, S.RETURNED)

    def test_removed_v0_endpoint_is_gone(self):
        self.assertEqual(self.client.get("/api/risk-review-v0/reviews/").status_code, 404)


class RuleConverseProxyTests(TestCase):
    """대화형 룰 수정 — 화면이 Django를 거쳐 Agent에 닿는다(FastAPI는 내부 전용)."""

    def setUp(self):
        self.graph = RuleGraph.objects.create(
            name="접대 초안", scope="접대", status=RuleGraphStatus.DRAFT, version=1,
        )
        self.client = APIClient()

    def _url(self, graph=None):
        return f"/api/rules/{(graph or self.graph).pk}/converse/"

    def _login(self, role=Role.ACCOUNTANT):
        User.objects.create_user("u1", password="pw", role=role)
        self.client.login(username="u1", password="pw")

    def test_requires_rule_view(self):
        User.objects.create_user("nobody", password="pw", role=Role.EMPLOYEE)
        self.client.login(username="nobody", password="pw")
        resp = self.client.post(self._url(), {"message": "x"}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_empty_message_is_rejected_before_calling_ai(self):
        self._login()
        with patch("domain.policies.views.httpx.post") as post:
            resp = self.client.post(self._url(), {"message": "   "}, format="json")
        self.assertEqual(resp.status_code, 400)
        post.assert_not_called()

    def test_active_graph_cannot_be_edited_by_chat(self):
        """대화로 ACTIVE를 고치면 시뮬레이션·승인 절차를 통째로 우회하게 된다."""
        active = RuleGraph.objects.create(
            name="활성", scope="식대", status=RuleGraphStatus.ACTIVE, version=1,
        )
        self._login()
        with patch("domain.policies.views.httpx.post") as post:
            resp = self.client.post(self._url(active), {"message": "바꿔줘"}, format="json")
        self.assertEqual(resp.status_code, 400)
        post.assert_not_called()

    def test_forwards_to_ai_and_returns_payload(self):
        self._login()
        payload = {"answer": "금액을 40만원으로 올렸어요", "applied_changes": [{"nodeKey": "n1"}], "graph": {}}
        with patch("domain.policies.views.httpx.post") as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = payload
            resp = self.client.post(self._url(), {"message": "40만원으로"}, format="json")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["answer"], "금액을 40만원으로 올렸어요")
        sent = post.call_args.kwargs["json"]
        self.assertEqual(sent["graph_id"], str(self.graph.pk))
        self.assertEqual(sent["message"], "40만원으로")

    def test_ai_down_reports_503(self):
        self._login()
        with patch("domain.policies.views.httpx.post", side_effect=OSError("연결 실패")):
            resp = self.client.post(self._url(), {"message": "x"}, format="json")
        self.assertEqual(resp.status_code, 503)
        self.assertIn("연결하지 못했습니다", resp.data["detail"])

    def test_accountant_lead_also_allowed(self):
        """룰 열람 capability만 있으면 된다 — 활성 권한까지 요구하지 않는다."""
        user = User.objects.create_user("acclead2", password="pw", role=Role.ACCOUNTANT_LEAD)
        self.assertIn(Capability.RULE_VIEW.value, user.capabilities)
        self.client.login(username="acclead2", password="pw")
        with patch("domain.policies.views.httpx.post") as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {"answer": "ok", "applied_changes": [], "graph": {}}
            resp = self.client.post(self._url(), {"message": "x"}, format="json")
        self.assertEqual(resp.status_code, 200)
