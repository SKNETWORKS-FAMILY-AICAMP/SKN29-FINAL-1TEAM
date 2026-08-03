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
    ragReport = serializers.CharField(source="rag_report", read_only=True)
    aiRecommendation = serializers.CharField(source="ai_recommendation", read_only=True)
    aiConfidence = serializers.FloatField(source="ai_confidence", read_only=True)

    class Meta:
        model = RiskReview
        fields = ["anomalyScore", "featureContribs", "ragRefs", "ragReport", "aiRecommendation", "aiConfidence"]


class SettlementEventSerializer(serializers.ModelSerializer):
    fromState = serializers.CharField(source="from_state", read_only=True)
    toState = serializers.CharField(source="to_state", read_only=True)
    actor = serializers.CharField(source="actor.username", read_only=True, default=None)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = SettlementEvent
        fields = ["id", "fromState", "toState", "actor", "reason", "createdAt"]


class SettlementSerializer(serializers.ModelSerializer):
    """목록/상세 공용 — 거래·부서·Risk 파생 필드를 평탄화(camelCase).

    프론트 Settlement/ReviewItem 셰이프와 정합. Risk 필드는 위험검토(IN_REVIEW) 건에만 채워진다.
    """
    date = serializers.SerializerMethodField()
    time = serializers.SerializerMethodField()
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
    dept = serializers.SerializerMethodField()
    # ── Risk 평탄화 (ReviewItem 셰이프) ──
    anomalyScore = serializers.SerializerMethodField()
    aiRecommendation = serializers.SerializerMethodField()
    aiConfidence = serializers.SerializerMethodField()
    featureContribs = serializers.SerializerMethodField()
    ragRefs = serializers.SerializerMethodField()
    ragReport = serializers.SerializerMethodField()
    anomalyReasons = serializers.SerializerMethodField()
    # 판정 시점 EvalContext 스냅샷(rule_hits) — 있으면 검토 화면의 fact.json이 이걸 보여준다.
    evalContext = serializers.SerializerMethodField()

    class Meta:
        model = Settlement
        fields = [
            "id", "date", "time", "merchant", "amount", "cardType",
            "category", "aiCategory", "aiSuggested", "merchantIndustry", "purpose",
            "evidence", "status", "statusLabel", "user", "dept",
            "anomalyScore", "aiRecommendation", "aiConfidence",
            "featureContribs", "ragRefs", "ragReport", "anomalyReasons", "evalContext",
        ]
        read_only_fields = ["status"]  # 상태 전이는 서비스(services.py)를 통해서만

    def get_date(self, obj):
        return obj.transaction.ts.date().isoformat() if obj.transaction_id else None

    def get_time(self, obj):
        return obj.transaction.ts.strftime("%H:%M") if obj.transaction_id else None

    def get_cardType(self, obj):
        card = getattr(obj.transaction, "card", None)
        return card.card_type if card else None

    def get_evidence(self, obj):
        # 증빙 '누락'은 하드 플래그로 차단하지 않는다 — 영수증 없이도 자동 유연처리 지원(AI가 별도 판단).
        # 영수증이 매칭되면 'OK', 없어도 누락으로 막지 않고 'OK'로 통과시킨다(누락 여부 판단은 AI 몫, post-MVP).
        return "OK"

    def get_dept(self, obj):
        return obj.submitted_by.team.name if (obj.submitted_by_id and obj.submitted_by.team_id) else None

    def _risk(self, obj):
        rrs = list(obj.risk_reviews.all())  # viewset에서 prefetch
        return rrs[0] if rrs else None

    def get_anomalyScore(self, obj):
        r = self._risk(obj)
        return r.anomaly_score if r else None

    def get_aiRecommendation(self, obj):
        r = self._risk(obj)
        return r.ai_recommendation if r else None

    def get_aiConfidence(self, obj):
        r = self._risk(obj)
        return r.ai_confidence if r else None

    def get_featureContribs(self, obj):
        r = self._risk(obj)
        return r.reasons if r else []

    def get_ragRefs(self, obj):
        r = self._risk(obj)
        return r.rag_refs if r else []

    def get_ragReport(self, obj):
        r = self._risk(obj)
        return r.rag_report if r else ""

    def get_anomalyReasons(self, obj):
        r = self._risk(obj)
        return r.anomaly_reasons if r else []

    def get_evalContext(self, obj):
        hits = list(obj.rule_hits.all())
        return hits[0].eval_context if hits and hits[0].eval_context else None


class SettlementDetailSerializer(SettlementSerializer):
    """상세: Audit Trail(상태 이력) + Risk(이상탐지+RAG) 포함."""
    events = SettlementEventSerializer(many=True, read_only=True)
    risk = serializers.SerializerMethodField()
    additionalEvidence = serializers.SerializerMethodField()
    facts = serializers.SerializerMethodField()
    ruleHits = serializers.SerializerMethodField()

    class Meta(SettlementSerializer.Meta):
        fields = SettlementSerializer.Meta.fields + [
            "events", "risk", "additionalEvidence", "facts", "ruleHits",
        ]

    def get_risk(self, obj):
        rr = obj.risk_reviews.first()
        return RiskReviewSerializer(rr).data if rr else None

    def get_additionalEvidence(self, obj):
        if not obj.transaction_id:
            return []
        return [
            {"id": receipt.id, "name": receipt.file_ref or f"증빙 #{receipt.id}", "status": receipt.status}
            for receipt in obj.transaction.receipts.all()
        ]

    def get_facts(self, obj):
        tx = obj.transaction
        card = tx.card if tx else None
        return {
            "settlement_id": obj.id,
            "transaction": {
                "merchant": tx.merchant,
                "amount": int(tx.amount),
                "occurred_at": tx.ts.isoformat(),
                "has_receipt": tx.receipts.filter(status="MATCHED").exists(),
            },
            "card": {"type": card.card_type if card else None, "name": card.name if card else None},
            "submitter": {
                "username": obj.submitted_by.username if obj.submitted_by_id else None,
                "team": obj.team.name if obj.team_id else None,
            },
            "settlement": {
                "category": obj.category,
                "ai_category": obj.ai_category,
                "merchant_industry": obj.merchant_industry,
                "purpose": obj.purpose,
                "status": obj.status,
            },
        }

    def get_ruleHits(self, obj):
        return [
            {
                "graph": hit.graph.name if hit.graph_id else None,
                "graphVersion": hit.graph_version,
                "path": hit.path,
                "decision": hit.decision,
                "confidence": hit.confidence,
            }
            for hit in obj.rule_hits.select_related("graph").all()
        ]
