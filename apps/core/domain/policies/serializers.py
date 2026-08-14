from rest_framework import serializers

from .models import PolicyDoc, RuleGraph, RuleGraphVersion, RuleNode, RuleRouting


class PolicyDocSerializer(serializers.ModelSerializer):
    """규정 문서 + 적재 결과. 화면은 `status`를 폴링해 진행을 본다."""
    statusLabel = serializers.CharField(source="get_status_display", read_only=True)
    fileName = serializers.SerializerMethodField()
    chunkCount = serializers.IntegerField(source="chunk_count", read_only=True)
    leafCount = serializers.IntegerField(source="leaf_count", read_only=True)
    ruleScope = serializers.CharField(source="rule_scope", read_only=True)
    # 적재 후 룰 생성 트리거 결과 — 지금은 "개발 중" 안내가 들어온다.
    ruleTrigger = serializers.JSONField(source="rule_trigger", read_only=True)
    indexedAt = serializers.DateTimeField(source="indexed_at", read_only=True)
    uploadedAt = serializers.DateTimeField(source="created_at", read_only=True)
    uploadedBy = serializers.CharField(source="uploaded_by.first_name", read_only=True, default="")

    class Meta:
        model = PolicyDoc
        fields = [
            "id", "title", "category", "version", "fileName", "profile", "collection",
            "status", "statusLabel", "chunkCount", "leafCount", "error",
            "ruleScope", "ruleTrigger", "indexedAt", "uploadedAt", "uploadedBy",
        ]

    def get_fileName(self, obj):
        return obj.file.name.rsplit("/", 1)[-1] if obj.file else ""


class RuleNodeSerializer(serializers.ModelSerializer):
    nodeKey = serializers.CharField(source="node_key", read_only=True)
    # 비개발자용 "이 Rule이 하는 일" 문장 — 저장된 값을 그대로 내려준다(프론트 DSL 파싱 대체).
    conditionText = serializers.CharField(source="condition_text", read_only=True)

    class Meta:
        model = RuleNode
        fields = ["id", "nodeKey", "condition", "conditionText", "action", "priority"]


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
    # Rule Agent 생성 이력(모델·질의·출처). 비어 있으면 사람이 만든 그래프다.
    generationMeta = serializers.JSONField(source="generation_meta", read_only=True)
    sourceClause = serializers.CharField(source="source_clause", read_only=True)
    familyKey = serializers.UUIDField(source="family_key", read_only=True)
    nodes = RuleNodeSerializer(many=True, read_only=True)
    routings = RuleRoutingSerializer(many=True, read_only=True)
    versions = RuleGraphVersionSerializer(many=True, read_only=True)
    # 검토자(Active 요청) · 활성자 추적
    reviewedBy = serializers.CharField(source="reviewed_by.first_name", read_only=True, default="")
    reviewedAt = serializers.DateTimeField(source="reviewed_at", read_only=True)
    reviewComment = serializers.CharField(source="review_comment", read_only=True)
    activatedBy = serializers.CharField(source="approved_by.first_name", read_only=True, default="")

    class Meta:
        model = RuleGraph
        fields = [
            "id", "familyKey", "name", "scope", "status", "statusLabel", "version",
            "entryNodeKey", "simResult", "sourceClause", "generationMeta", "activated_at",
            "reviewedBy", "reviewedAt", "reviewComment", "activatedBy",
            "nodes", "routings", "versions",
        ]


class RuleGraphListSerializer(serializers.ModelSerializer):
    statusLabel = serializers.CharField(source="get_status_display", read_only=True)
    sourceClause = serializers.CharField(source="source_clause", read_only=True)
    simResult = serializers.JSONField(source="sim_result", read_only=True)
    # Rule Agent 생성 이력(모델·질의·출처). 비어 있으면 사람이 만든 그래프다.
    generationMeta = serializers.JSONField(source="generation_meta", read_only=True)
    nodeCount = serializers.IntegerField(source="nodes.count", read_only=True)
    familyKey = serializers.UUIDField(source="family_key", read_only=True)
    entryNodeKey = serializers.CharField(source="entry_node_key", read_only=True)
    nodes = RuleNodeSerializer(many=True, read_only=True)
    routings = RuleRoutingSerializer(many=True, read_only=True)
    versions = RuleGraphVersionSerializer(many=True, read_only=True)
    reviewedBy = serializers.CharField(source="reviewed_by.first_name", read_only=True, default="")
    reviewedAt = serializers.DateTimeField(source="reviewed_at", read_only=True)
    reviewComment = serializers.CharField(source="review_comment", read_only=True)
    activatedBy = serializers.CharField(source="approved_by.first_name", read_only=True, default="")

    class Meta:
        model = RuleGraph
        fields = [
            "id", "familyKey", "name", "scope", "status", "statusLabel", "version",
            "entryNodeKey", "sourceClause", "simResult", "generationMeta", "nodeCount", "activated_at",
            "reviewedBy", "reviewedAt", "reviewComment", "activatedBy",
            "nodes", "routings", "versions",
        ]
