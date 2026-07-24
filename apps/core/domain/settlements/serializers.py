from rest_framework import serializers

from .models import Settlement, SettlementEvent


class SettlementEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.username", read_only=True, default=None)

    class Meta:
        model = SettlementEvent
        fields = ["id", "from_state", "to_state", "actor", "actor_name", "reason", "created_at"]


class SettlementSerializer(serializers.ModelSerializer):
    """목록/상세 공용. 거래 파생 필드를 평탄화해 프론트 렌더 편의를 제공."""
    merchant = serializers.CharField(source="transaction.merchant", read_only=True)
    amount = serializers.DecimalField(
        source="transaction.amount", max_digits=12, decimal_places=0, read_only=True
    )
    date = serializers.SerializerMethodField()
    card_type = serializers.SerializerMethodField()
    evidence = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    submitted_by_name = serializers.CharField(source="submitted_by.username", read_only=True, default=None)

    class Meta:
        model = Settlement
        fields = [
            "id", "transaction", "date", "merchant", "amount", "card_type",
            "category", "ai_category", "ai_suggested", "merchant_industry",
            "evidence", "status", "status_label",
            "submitted_by", "submitted_by_name", "team", "created_at", "updated_at",
        ]
        # 상태 전이는 서비스(services.py)를 통해서만 — 직접 PATCH 금지.
        read_only_fields = ["status", "created_at", "updated_at"]

    def get_date(self, obj):
        return obj.transaction.ts.date().isoformat() if obj.transaction_id else None

    def get_card_type(self, obj):
        card = getattr(obj.transaction, "card", None)
        return card.card_type if card else None

    def get_evidence(self, obj):
        if obj.transaction_id and obj.transaction.receipts.filter(status="MATCHED").exists():
            return "OK"
        return "MISSING"


class SettlementDetailSerializer(SettlementSerializer):
    """상세: Audit Trail(상태 이력) 포함."""
    events = SettlementEventSerializer(many=True, read_only=True)

    class Meta(SettlementSerializer.Meta):
        fields = SettlementSerializer.Meta.fields + ["events"]
