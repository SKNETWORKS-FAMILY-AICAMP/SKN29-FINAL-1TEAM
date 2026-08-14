# apps/core/domain/risk_review_v0/views.py
"""Review List v0 — 독립 개발 서브패키지 (조회 API + 처리 API).

⚠️ 데이터 계층은 격리하지 않는다: `domain.settlements`/`domain.risk`의 실제 운영 모델을
그대로 import한다(신규 모델·mock DB·fixture 금지). `rule_agent_v0`의 `search_policy`가
로컬 Chroma로 격리돼 운영 인덱스와 분리된 채 "죽은 경로"가 됐던 사례(risk_review_agent
세션에서 확인)의 재발 방지가 이 파일의 존재 이유 — 여기서 대상이 DB라 더 치명적이었을 것.

v0 스코프:
  - GET  /api/risk-review-v0/reviews/            IN_REVIEW 목록, anomaly_score 내림차순
  - POST /api/risk-review-v0/reviews/<id>/decision/  승인/보완/반려

기존 상태 전이 서비스(`domain.settlements.services.review`)를 그대로 재사용한다 — 새
상태머신·새 저장 로직을 만들지 않는다. decision_labels 적재는 그 서비스가 이미 한다.
재학습 트리거는 없다(FR-RL-02, post-MVP 범위) — 이 패키지가 만들지 않는다.
"""
from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from domain.common.permissions import CanAccountingReview
from domain.risk.models import RiskReview
from domain.settlements import services
from domain.settlements.models import Settlement
from domain.settlements.models import SettlementStatus as S

from .serializers import ReviewListItemSerializer


def _actor(request):
    user = getattr(request, "user", None)
    return user if (user and user.is_authenticated) else None


class ReviewListView(APIView):
    """GET /api/risk-review-v0/reviews/ — IN_REVIEW 건 + 최신 risk_reviews, anomaly_score 내림차순."""

    permission_classes = [CanAccountingReview]

    def get(self, request):
        settlements = list(
            Settlement.objects.filter(status=S.IN_REVIEW)
            .select_related("transaction", "submitted_by")
        )
        # settlement당 최신(-id) 1건만 — order_by가 (settlement_id, -id) 순이라 첫 등장이 최신이다.
        latest_reviews: dict[int, RiskReview] = {}
        for review in RiskReview.objects.filter(settlement__in=settlements).order_by("settlement_id", "-id"):
            latest_reviews.setdefault(review.settlement_id, review)

        settlements.sort(
            key=lambda s: latest_reviews[s.id].anomaly_score if s.id in latest_reviews else 0.0,
            reverse=True,
        )
        data = ReviewListItemSerializer(
            settlements, many=True, context={"reviews": latest_reviews}
        ).data
        return Response(data)


class ReviewDecisionView(APIView):
    """POST /api/risk-review-v0/reviews/<settlement_id>/decision/  {decision, reason?}

    decision: APPROVE(→PENDING_CONFIRM) | RETURN(→RETURNED) | REJECT(→REJECT).
    RETURN/REJECT는 사유 필수 — `services.review`가 이미 강제한다.
    """

    permission_classes = [CanAccountingReview]

    def post(self, request, settlement_id):
        settlement = Settlement.objects.filter(pk=settlement_id).first()
        if settlement is None:
            return Response({"detail": "정산을 찾을 수 없습니다."}, status=404)
        decision = str(request.data.get("decision", ""))
        reason = str(request.data.get("reason", ""))
        try:
            services.review(settlement, decision, _actor(request), reason)
        except services.TransitionError as e:
            return Response({"detail": str(e)}, status=400)
        return Response({"settlement_id": settlement.pk, "status": settlement.status})
