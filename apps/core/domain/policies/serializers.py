from rest_framework import serializers

from .models import RuleGraph, RuleGraphVersion, RuleNode, RuleRouting


class RuleNodeSerializer(serializers.ModelSerializer):
    nodeKey = serializers.CharField(source="node_key", read_only=True)

    class Meta:
        model = RuleNode
        fields = ["id", "nodeKey", "condition", "action", "priority"]


class RuleRoutingSerializer(serializers.ModelSerializer):
    fromNodeKey = serializers.CharField(source="from_node_key", read_only=True)
    onResult = serializers.CharField(source="on_result", read_only=True)
    toNodeKey = serializers.CharField(source="to_node_key", read_only=True)

    class Meta:
        model = RuleRouting
        fields = ["id", "fromNodeKey", "onResult", "toNodeKey", "priority"]


class RuleGraphVersionSerializer(serializers.ModelSerializer):
    isActive = serializers.BooleanField(source="is_active", read_only=True)

    class Meta:
        model = RuleGraphVersion
        fields = ["id", "version", "approved_by", "approved_at", "isActive"]


class RuleGraphSerializer(serializers.ModelSerializer):
    """룰 그래프(최종 상태 도메인) — 노드·라우팅·버전 이력 포함."""
    statusLabel = serializers.CharField(source="get_status_display", read_only=True)
    entryNodeKey = serializers.CharField(source="entry_node_key", read_only=True)
    simResult = serializers.JSONField(source="sim_result", read_only=True)
    sourceClause = serializers.CharField(source="source_clause", read_only=True)
    nodes = RuleNodeSerializer(many=True, read_only=True)
    routings = RuleRoutingSerializer(many=True, read_only=True)
    versions = RuleGraphVersionSerializer(many=True, read_only=True)

    class Meta:
        model = RuleGraph
        fields = [
            "id", "name", "scope", "status", "statusLabel", "version",
            "entryNodeKey", "simResult", "sourceClause", "activated_at",
            "nodes", "routings", "versions",
        ]


class RuleGraphListSerializer(serializers.ModelSerializer):
    statusLabel = serializers.CharField(source="get_status_display", read_only=True)
    sourceClause = serializers.CharField(source="source_clause", read_only=True)
    simResult = serializers.JSONField(source="sim_result", read_only=True)
    nodeCount = serializers.IntegerField(source="nodes.count", read_only=True)

    class Meta:
        model = RuleGraph
        fields = ["id", "name", "scope", "status", "statusLabel", "version",
                  "sourceClause", "simResult", "nodeCount"]
