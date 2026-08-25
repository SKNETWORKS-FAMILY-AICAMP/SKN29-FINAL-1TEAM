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
from domain.settlements import services
from domain.settlements.models import Attachment, Settlement
from domain.settlements.models import SettlementStatus as S
from domain.transactions.models import Transaction

# FastAPI `/agent/risk-review` 응답 모양(1차 이상탐지 + 2차 RAG 검증).
AI_RESPONSE = {
    "stage1_anomaly": {
        "anomaly_score": 0.87,
        "contribs": [{"feature": "amount", "weight": 0.4}],
        # 1차 점수의 3단계 등급. AI가 판정 시점 임계값으로 매겨 보내는 값이다.
        "risk_tier": "HIGH",
    },
    "stage2_rag_review": {
        "violation_verdict": "VIOLATION",
        "review_reasons": ["1인당 한도 초과"],
        "recommendation": "SUPPLEMENT",
        "citations": [{"doc": "회식_사용규정", "article": "제5조", "quote_summary": "1인당 5만원"}],
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
        # 1차 등급이 실제로 저장된다 — 예전엔 AI가 보내도 여기서 조용히 버려져서,
        # 3단계 분류 기능이 DB·화면 어디에도 닿지 않았다(2026-08-19 전수 검토에서 발견).
        self.assertEqual(review.risk_tier, "HIGH")
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


class ReviewStatsTests(TestCase):
    """S-03 헤더 요약 지표(`/api/settlements/review-stats/`) — 예전엔 82%/6.2분이 하드코딩이었다.

    자동처리율은 **룰 엔진 자체 판정**(`rule_decision`) 기준이다 — REVIEW만 사람에게 넘어가고
    PASS/RETURN/REJECT는 룰이 그 자리에서 끝냈다는 뜻이라 "사람 손 없이 처리된 비율"의 정확한
    정의다. 평균 검토시간은 `SettlementEvent`의 IN_REVIEW 진입→이탈 시각차 평균이다.
    """

    def setUp(self):
        self.acc = User.objects.create_user("acc2", password="pw", role=Role.ACCOUNTANT)
        self.client = APIClient()
        self.client.login(username="acc2", password="pw")

    def _submit(self, scope, decision):
        _graph(scope, decision)
        card = Card.objects.create(name="법인카드", card_type="SHARED")
        tx = Transaction.objects.create(
            card=card, merchant="가맹점", amount=Decimal("10000"), ts=timezone.now(),
        )
        s = Settlement.objects.create(
            transaction=tx, category=scope, status=S.TEAM_COLLECTING, purpose=scope,
        )
        with patch("domain.settlements.risk_review.httpx.post") as post:
            post.return_value.json.return_value = AI_RESPONSE
            post.return_value.raise_for_status.return_value = None
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post("/api/settlements/submit/", {"ids": [s.pk]}, format="json")
        s.refresh_from_db()
        return s

    def test_pass_decision_counts_as_auto_processed(self):
        """REVIEW로 안 떨어진 건은 사람 손이 필요 없었다는 뜻 — 자동처리율에 반영된다."""
        self._submit("회의", "PASS")
        resp = self.client.get("/api/settlements/review-stats/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["totalJudged"], 1)
        self.assertEqual(resp.data["autoProcessedRate"], 1.0)
        self.assertEqual(resp.data["reviewedCount"], 0)
        self.assertIsNone(resp.data["avgReviewMinutes"])

    def test_review_decision_lowers_auto_processed_rate_and_measures_duration(self):
        """REVIEW로 떨어져 사람이 결정을 내리면 자동처리율이 낮아지고 소요시간이 잡힌다."""
        s = self._submit("접대", "REVIEW")
        self.assertEqual(s.status, S.IN_REVIEW)
        services.review(s, "APPROVE", self.acc)

        resp = self.client.get("/api/settlements/review-stats/")
        self.assertEqual(resp.data["totalJudged"], 1)
        self.assertEqual(resp.data["autoProcessedRate"], 0.0)
        self.assertEqual(resp.data["reviewedCount"], 1)
        self.assertIsNotNone(resp.data["avgReviewMinutes"])
        self.assertGreaterEqual(resp.data["avgReviewMinutes"], 0.0)

    def test_no_data_this_month_returns_null_rate_not_zero(self):
        """판정 자체가 없으면 0%가 아니라 '집계 불가'(null)다 — 0%는 실제로 다 실패했다는 뜻."""
        resp = self.client.get("/api/settlements/review-stats/")
        self.assertEqual(resp.data["totalJudged"], 0)
        self.assertIsNone(resp.data["autoProcessedRate"])

    def test_requires_accounting_review_capability(self):
        User.objects.create_user("emp2", password="pw", role=Role.EMPLOYEE)
        client = APIClient()
        client.login(username="emp2", password="pw")
        resp = client.get("/api/settlements/review-stats/")
        self.assertEqual(resp.status_code, 403)


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
            rag_refs=[{"title": "1인당 5만원", "source": "회식_사용규정 제5조", "kind": "policy"}],
            ai_recommendation="RETURN",
            risk_tier="HIGH",
            stage2_verdict={"violation_verdict": "VIOLATION", "recommendation": "SUPPLEMENT"},
        )
        resp = self.client.get(f"/api/settlements/{self.settlement.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["anomalyScore"], 0.91)
        # 원시 점수는 사람이 크기를 가늠할 수 없어(실측 −0.03~+0.06) 화면은 등급으로 읽는다.
        self.assertEqual(resp.data["riskTier"], "HIGH")
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
        # 등급도 같은 계약 — 안 돈 건은 ''(등급 없음)이지 'LOW'(안전함)가 아니다.
        self.assertEqual(resp.data["riskTier"], "")

    def test_rejudged_settlement_shows_the_latest_review_not_the_highest_scored(self):
        """재판정은 행을 새로 쌓는다(갱신이 아니다) — 화면은 **최신** 판정을 봐야 한다.

        실측 재현: 정렬이 `-anomaly_score`였을 때, 점수가 같은 옛 행이 새 행을 가려서
        재판정 후에도 검토 화면에 이전 결과(등급 없음·옛 권고)가 떴다.
        """
        RiskReview.objects.create(
            settlement=self.settlement, anomaly_score=0.9, risk_tier="",
            ai_recommendation="APPROVE",
            stage2_verdict={"violation_verdict": "NO_VIOLATION"},
        )
        latest = RiskReview.objects.create(
            settlement=self.settlement, anomaly_score=0.9, risk_tier="HIGH",
            ai_recommendation="RETURN",
            stage2_verdict={"violation_verdict": "VIOLATION"},
        )

        resp = self.client.get(f"/api/settlements/{self.settlement.pk}/")
        self.assertEqual(resp.data["riskTier"], "HIGH")
        self.assertEqual(resp.data["violationVerdict"], "VIOLATION")
        self.assertEqual(resp.data["aiRecommendation"], "RETURN")
        self.assertEqual(self.settlement.risk_reviews.first().pk, latest.pk)

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


class AttachmentConfidenceGateTests(TestCase):
    """저신뢰 추출값은 판정에 반영되지 않는다(`_context/evidence-extraction-agent.md` §6 결정 2).

    "적용하되 표시"가 아니라 **미해소로 남긴다** — 값 자체는 `Attachment.extracted`에
    그대로 남아 화면 표시(E-6)에는 쓸 수 있지만, EvalContext에는 올라가지 않는다.
    """

    def setUp(self):
        card = Card.objects.create(name="법인카드", card_type="PERSONAL")
        tx = Transaction.objects.create(card=card, merchant="강남 한식당", amount=Decimal("120000"), ts=timezone.now())
        self.settlement = Settlement.objects.create(transaction=tx, category="접대", status=S.DRAFT)

    def test_low_confidence_extraction_is_not_offered_to_eval_context(self):
        from domain.policies.context_builder import FactMerger, collect_from_attachments

        Attachment.objects.create(
            settlement=self.settlement, kind="PRE_APPROVAL", extraction_status="DONE",
            extracted={"approval.pre_approval_obtained": True},
            field_confidence={"approval.pre_approval_obtained": 0.4},  # 임계값(0.6) 미만
            extracted_at=timezone.now(),
        )
        merger = FactMerger()
        collect_from_attachments(merger, self.settlement)
        self.assertIsNone(merger.resolved("approval.pre_approval_obtained"))

    def test_high_confidence_extraction_is_offered(self):
        from domain.policies.context_builder import FactMerger, collect_from_attachments

        Attachment.objects.create(
            settlement=self.settlement, kind="PRE_APPROVAL", extraction_status="DONE",
            extracted={"approval.pre_approval_obtained": True},
            field_confidence={"approval.pre_approval_obtained": 0.9},
            extracted_at=timezone.now(),
        )
        merger = FactMerger()
        collect_from_attachments(merger, self.settlement)
        self.assertTrue(merger.resolved("approval.pre_approval_obtained"))
