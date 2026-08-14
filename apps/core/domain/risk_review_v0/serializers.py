# apps/core/domain/risk_review_v0/serializers.py
"""Review List v0 응답 셰이프 — 운영 모델(Settlement/RiskReview)을 그대로 직렬화한다.

stage2_verdict는 가공 없이 원본 구조 그대로 노출(citations/similar_cases 포함). feature_contribs
(=RiskReview.reasons)도 있는 그대로 노출한다 — 이 pkl 세대엔 feature_stats가 없어 빈 배열일 수
있는데(v0 알려진 한계, CLAUDE.md 참조), 여기서 그걸 감추거나 채워 넣지 않는다.
"""
from __future__ import annotations

from rest_framework import serializers


class ReviewListItemSerializer(serializers.Serializer):
    """GET 목록 항목 — 최신 RiskReview는 context["reviews"][settlement.id]로 주입받는다."""

    id = serializers.IntegerField()
    merchant = serializers.SerializerMethodField()
    amount = serializers.SerializerMethodField()
    category = serializers.CharField()
    purpose = serializers.CharField()
    status = serializers.CharField()
    submittedBy = serializers.SerializerMethodField()
    submittedAt = serializers.SerializerMethodField()
    anomalyScore = serializers.SerializerMethodField()
    featureContribs = serializers.SerializerMethodField()
    violationVerdict = serializers.SerializerMethodField()
    recommendation = serializers.SerializerMethodField()
    stage2Verdict = serializers.SerializerMethodField()

    def _review(self, obj):
        return self.context.get("reviews", {}).get(obj.id)

    def get_merchant(self, obj):
        return obj.transaction.merchant

    def get_amount(self, obj):
        return int(obj.transaction.amount)

    def get_submittedBy(self, obj):
        u = obj.submitted_by
        return (getattr(u, "first_name", "") or getattr(u, "username", "")) if u else ""

    def get_submittedAt(self, obj):
        return obj.transaction.ts

    def get_anomalyScore(self, obj):
        review = self._review(obj)
        return review.anomaly_score if review else 0.0

    def get_featureContribs(self, obj):
        review = self._review(obj)
        return review.reasons if review else []

    def get_violationVerdict(self, obj):
        review = self._review(obj)
        return (review.stage2_verdict or {}).get("violation_verdict", "") if review else ""

    def get_recommendation(self, obj):
        review = self._review(obj)
        return (review.stage2_verdict or {}).get("recommendation", "") if review else ""

    def get_stage2Verdict(self, obj):
        review = self._review(obj)
        return review.stage2_verdict if review else {}
