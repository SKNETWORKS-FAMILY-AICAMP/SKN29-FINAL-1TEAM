"""정산 직렬화 — 프론트 `types/domain.ts`의 Settlement(camelCase)와 정합.

프론트가 USE_MOCK=false로 전환하면 이 셰이프를 그대로 소비한다.
"""
from rest_framework import serializers

from domain.risk.models import RiskReview

from .models import Settlement, SettlementEvent


class RiskReviewSerializer(serializers.ModelSerializer):
    anomalyScore = serializers.FloatField(source="anomaly_score", read_only=True)
    featureContribs = serializers.JSONField(source="reasons", read_only=True)
    ragRefs = serializers.JSONField(source="rag_refs", read_only=True)
    aiRecommendation = serializers.CharField(source="ai_recommendation", read_only=True)
    aiConfidence = serializers.FloatField(source="ai_confidence", read_only=True)

    class Meta:
        model = RiskReview
        fields = ["anomalyScore", "featureContribs", "ragRefs", "aiRecommendation", "aiConfidence"]


class SettlementEventSerializer(serializers.ModelSerializer):
    fromState = serializers.CharField(source="from_state", read_only=True)
    toState = serializers.CharField(source="to_state", read_only=True)
    actor = serializers.CharField(source="actor.username", read_only=True, default=None)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = SettlementEvent
        fields = ["id", "fromState", "toState", "actor", "reason", "createdAt"]


class SettlementSerializer(serializers.ModelSerializer):
    """목록/상세 공용 — 거래 파생 필드를 평탄화(camelCase)."""
    date = serializers.SerializerMethodField()
    merchant = serializers.CharField(source="transaction.merchant", read_only=True)
    amount = serializers.DecimalField(
        source="transaction.amount", max_digits=12, decimal_places=0, read_only=True
    )
    cardType = serializers.SerializerMethodField()
    aiCategory = serializers.CharField(source="ai_category", read_only=True)
    aiSuggested = serializers.BooleanField(source="ai_suggested", read_only=True)
    merchantIndustry = serializers.CharField(source="merchant_industry", read_only=True)
    evidence = serializers.SerializerMethodField()
    statusLabel = serializers.CharField(source="get_status_display", read_only=True)
    user = serializers.CharField(source="submitted_by.username", read_only=True, default=None)

    class Meta:
        model = Settlement
        fields = [
            "id", "date", "merchant", "amount", "cardType",
            "category", "aiCategory", "aiSuggested", "merchantIndustry",
            "evidence", "status", "statusLabel", "user",
        ]
        read_only_fields = ["status"]  # 상태 전이는 서비스(services.py)를 통해서만

    def get_date(self, obj):
        return obj.transaction.ts.date().isoformat() if obj.transaction_id else None

    def get_cardType(self, obj):
        card = getattr(obj.transaction, "card", None)
        return card.card_type if card else None

    def get_evidence(self, obj):
        if obj.transaction_id and obj.transaction.receipts.filter(status="MATCHED").exists():
            return "OK"
        return "MISSING"


class SettlementDetailSerializer(SettlementSerializer):
    """상세: Audit Trail(상태 이력) + Risk(이상탐지+RAG) 포함."""
    events = SettlementEventSerializer(many=True, read_only=True)
    risk = serializers.SerializerMethodField()

    class Meta(SettlementSerializer.Meta):
        fields = SettlementSerializer.Meta.fields + ["events", "risk"]

    def get_risk(self, obj):
        rr = obj.risk_reviews.first()
        return RiskReviewSerializer(rr).data if rr else None
