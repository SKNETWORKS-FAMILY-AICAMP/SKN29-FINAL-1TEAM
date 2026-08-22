"""Risk Review **진행 상태** 회귀.

## 왜 상태를 따로 기록하나

이상탐지 + RAG 내규검증은 커밋 후 비동기로 돈다(최대 60초). 그 사이 `risk_reviews`가
비어 있는데, **「결과가 없다」는 세 가지 다른 상황을 뭉갠다**:

  · 룰이 통과시켜 **대상이 아니다**
  · 예약돼 **돌고 있다**
  · 돌았는데 **실패**했다

결과 유무만 보던 화면은 이 셋을 구분하지 못해, 검토 중인 건에 "룰 판정으로 통과된
건입니다"라는 안내를 띄웠다. 경과 시간으로 추정하지 않고 실제 상태를 기록한다
(첨부 판독 `Attachment.extraction_status`와 같은 규율).
"""
from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from domain.accounts.models import Role, Team, User
from domain.cards.models import Card, CardType
from domain.settlements import risk_review, services
from domain.settlements.models import (
    Category, RiskReviewState, Settlement, SettlementStatus as S,
)
from domain.settlements.serializers import SettlementSerializer
from domain.transactions.models import Receipt, Transaction

AI_RESULT = {
    "stage1_anomaly": {"anomaly_score": 0.42, "contribs": []},
    "stage2_rag_review": {"review_reasons": [], "citations": [], "similar_cases": [],
                          "recommendation": "APPROVE", "violation_verdict": "NO_VIOLATION"},
}


class RiskReviewStateTests(TestCase):
    def setUp(self):
        call_command("seed_clean", verbosity=0)
        self.user = User.objects.get(username="kim")
        self.card = Card.objects.filter(card_type=CardType.PERSONAL).first()

    def _settlement(self, *, receipt=True, **kwargs):
        tx = Transaction.objects.create(card=self.card, merchant="카페",
                                        amount=Decimal("9000"), ts=timezone.now())
        if receipt:
            Receipt.objects.create(matched_tx=tx, status="MATCHED", file_ref="r.jpg")
        defaults = dict(
            transaction=tx, submitted_by=self.user, team=self.user.team, status=S.DRAFT,
            category=Category.MEAL, purpose="팀 회의 음료",
            merchant_industry="카페", merchant_industry_code="CAFE",
        )
        defaults.update(kwargs)
        return Settlement.objects.create(**defaults)

    def _to_review(self, settlement):
        """검토(IN_REVIEW)까지 실제 경로로 보낸다 — 증빙이 없으면 자동 통과 요건에 못 미친다."""
        services.raise_to_team(settlement, self.user)
        services.submit(settlement, self.user)
        services.judge(settlement, self.user)
        settlement.refresh_from_db()

    # ── 대상이 아니다 ────────────────────────────────────────────────
    def test_룰_통과_건은_미실시로_남는다(self):
        settlement = self._settlement()
        with self.captureOnCommitCallbacks(execute=True):
            self._to_review(settlement)
        self.assertEqual(settlement.status, S.PENDING_CONFIRM)
        self.assertEqual(settlement.risk_review_state, RiskReviewState.NOT_STARTED)

    # ── 돌고 있다 ────────────────────────────────────────────────────
    def test_검토로_가면_예약과_동시에_RUNNING이_기록된다(self):
        """**커밋 전에** 기록해야 한다 — 실행은 커밋 후라 그 사이 화면이 목록을 읽는다."""
        settlement = self._settlement(receipt=False)
        with patch("domain.settlements.risk_review.run") as run:
            with self.captureOnCommitCallbacks(execute=False):   # 콜백을 일부러 안 돌린다
                self._to_review(settlement)
            run.assert_not_called()
        self.assertEqual(settlement.status, S.IN_REVIEW)
        self.assertEqual(settlement.risk_review_state, RiskReviewState.RUNNING)
        self.assertIsNotNone(settlement.risk_review_started_at)

        # 이 시점 화면이 읽는 값 — 「검토 중」이라고 말할 수 있어야 한다.
        data = SettlementSerializer(settlement).data
        self.assertEqual(data["riskReviewState"], "RUNNING")
        self.assertFalse(data["riskReviewed"])

    # ── 끝났다 ───────────────────────────────────────────────────────
    def test_결과가_저장되면_DONE이_된다(self):
        settlement = self._settlement(receipt=False)
        with patch("domain.settlements.risk_review.httpx.post") as post:
            post.return_value.json.return_value = AI_RESULT
            post.return_value.raise_for_status.return_value = None
            with self.captureOnCommitCallbacks(execute=True):
                self._to_review(settlement)
        settlement.refresh_from_db()
        self.assertEqual(settlement.risk_review_state, RiskReviewState.DONE)
        self.assertTrue(settlement.risk_reviews.exists())
        self.assertEqual(SettlementSerializer(settlement).data["riskReviewState"], "DONE")

    # ── 실패했다 ─────────────────────────────────────────────────────
    def test_실패하면_사유와_함께_FAILED로_남는다(self):
        """안 남기면 화면이 「아직 도는 중」과 구분하지 못해 오지 않을 결과를 계속 기다린다."""
        settlement = self._settlement(receipt=False)
        with patch("domain.settlements.risk_review.httpx.post", side_effect=RuntimeError("ai down")):
            with self.captureOnCommitCallbacks(execute=True):
                self._to_review(settlement)
        settlement.refresh_from_db()
        self.assertEqual(settlement.risk_review_state, RiskReviewState.FAILED)
        self.assertIn("ai down", settlement.risk_review_error)
        data = SettlementSerializer(settlement).data
        self.assertEqual(data["riskReviewState"], "FAILED")
        self.assertIn("ai down", data["riskReviewError"])

    # ── 재실행 ───────────────────────────────────────────────────────
    def test_실패한_건을_다시_실행할_수_있다(self):
        settlement = self._settlement(receipt=False)
        with patch("domain.settlements.risk_review.httpx.post", side_effect=RuntimeError("ai down")):
            with self.captureOnCommitCallbacks(execute=True):
                self._to_review(settlement)

        client = APIClient()
        client.force_authenticate(User.objects.get(username="acc"))
        with patch("domain.settlements.risk_review.httpx.post") as post:
            post.return_value.json.return_value = AI_RESULT
            post.return_value.raise_for_status.return_value = None
            with self.captureOnCommitCallbacks(execute=True):
                r = client.post(f"/api/settlements/{settlement.id}/risk-review/", {}, format="json")
        self.assertEqual(r.status_code, 200)
        settlement.refresh_from_db()
        self.assertEqual(settlement.risk_review_state, RiskReviewState.DONE)

    def test_검토중이_아닌_건은_재실행할_수_없다(self):
        settlement = self._settlement()
        with self.captureOnCommitCallbacks(execute=True):
            self._to_review(settlement)          # → PENDING_CONFIRM
        client = APIClient()
        client.force_authenticate(User.objects.get(username="acc"))
        r = client.post(f"/api/settlements/{settlement.id}/risk-review/", {}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_재실행하면_이전_실패_사유가_지워진다(self):
        """옛 사유가 남아 있으면 새로 도는 중인데도 실패 메시지가 화면에 붙어 있다."""
        settlement = self._settlement(receipt=False)
        with patch("domain.settlements.risk_review.httpx.post", side_effect=RuntimeError("ai down")):
            with self.captureOnCommitCallbacks(execute=True):
                self._to_review(settlement)

        with patch("domain.settlements.risk_review.run"):
            with self.captureOnCommitCallbacks(execute=False):
                risk_review.schedule(settlement)
        settlement.refresh_from_db()
        self.assertEqual(settlement.risk_review_state, RiskReviewState.RUNNING)
        self.assertEqual(settlement.risk_review_error, "")
