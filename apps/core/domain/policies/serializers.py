from rest_framework import serializers

from .models import RuleGraph, RuleGraphVersion, RuleNode, RuleRouting


class RuleNodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RuleNode
        fields = ["id", "node_key", "condition", "action", "priority"]


class RuleRoutingSerializer(serializers.ModelSerializer):
    class Meta:
        model = RuleRouting
        fields = ["id", "from_node_key", "on_result", "to_node_key", "priority"]


class RuleGraphVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RuleGraphVersion
        fields = ["id", "version", "approved_by", "approved_at", "is_active"]


class RuleGraphSerializer(serializers.ModelSerializer):
    """룰 그래프(최종 상태 도메인) — 노드·라우팅·버전 이력 포함."""
    nodes = RuleNodeSerializer(many=True, read_only=True)
    routings = RuleRoutingSerializer(many=True, read_only=True)
    versions = RuleGraphVersionSerializer(many=True, read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = RuleGraph
        fields = [
            "id", "name", "scope", "status", "status_label", "version",
            "entry_node_key", "sim_result", "source_clause",
            "approved_by", "activated_at", "created_at",
            "nodes", "routings", "versions",
        ]


class RuleGraphListSerializer(serializers.ModelSerializer):
    """목록용 경량 직렬화(노드/라우팅 제외)."""
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    node_count = serializers.IntegerField(source="nodes.count", read_only=True)

    class Meta:
        model = RuleGraph
        fields = ["id", "name", "scope", "status", "status_label", "version",
                  "source_clause", "sim_result", "node_count", "created_at"]
