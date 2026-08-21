"""카드 직렬화 — 프론트(S-09)가 쓰는 camelCase 셰이프.

`usage`·`attention`은 모델 필드가 아니라 **요청 시점 계산값**이라 컨텍스트로 받는다
(뷰가 한 번만 집계해 넘긴다 — 행마다 쿼리를 돌면 카드 수만큼 N+1이 된다).
"""
from rest_framework import serializers

from .models import Card


class CardSerializer(serializers.ModelSerializer):
    type = serializers.CharField(source="card_type", read_only=True)
    typeLabel = serializers.CharField(source="get_card_type_display", read_only=True)
    number = serializers.CharField(source="number_masked", read_only=True)
    limit = serializers.IntegerField(source="limit_amount", read_only=True)
    statusLabel = serializers.CharField(source="get_status_display", read_only=True)
    stoppedReason = serializers.CharField(source="stopped_reason", read_only=True)
    stoppedAt = serializers.DateTimeField(source="stopped_at", read_only=True)
    assignee = serializers.CharField(source="assignee_label", read_only=True)
    teamId = serializers.IntegerField(source="team_id", read_only=True)
    teamName = serializers.SerializerMethodField()
    ownerId = serializers.IntegerField(source="owner_id", read_only=True)
    usage = serializers.SerializerMethodField()
    attention = serializers.SerializerMethodField()

    class Meta:
        model = Card
        fields = [
            "id", "name", "number", "type", "typeLabel", "assignee",
            "teamId", "teamName", "ownerId",
            "usage", "limit", "status", "statusLabel", "stoppedReason", "stoppedAt",
            "attention",
        ]

    def get_teamName(self, obj) -> str | None:
        if obj.team_id:
            return obj.team.name
        return obj.owner.team.name if (obj.owner_id and obj.owner.team_id) else None

    def get_usage(self, obj) -> int:
        return int((self.context.get("usage") or {}).get(obj.id, 0))

    def get_attention(self, obj) -> dict | None:
        from .views import attention_of

        return attention_of(obj, self.context.get("anomalies") or {})
