from rest_framework import serializers

from .models import PolicyDoc, RuleGraph, RuleGraphVersion, RuleNode, RuleRouting


class PolicyDocSerializer(serializers.ModelSerializer):
    """규정 문서 + 적재 결과. 화면은 `status`를 폴링해 진행을 본다."""
    statusLabel = serializers.CharField(source="get_status_display", read_only=True)
    fileName = serializers.SerializerMethodField()
    chunkCount = serializers.IntegerField(source="chunk_count", read_only=True)
    leafCount = serializers.IntegerField(source="leaf_count", read_only=True)
    ruleScope = serializers.CharField(source="rule_scope", read_only=True)
    # 적재 후 룰 자동 생성 트리거 결과 — 생성기의 status를 그대로(뭉개지 않고) 노출한다.
    ruleTrigger = serializers.JSONField(source="rule_trigger", read_only=True)
    indexedAt = serializers.DateTimeField(source="indexed_at", read_only=True)
    uploadedAt = serializers.DateTimeField(source="created_at", read_only=True)
    uploadedBy = serializers.CharField(source="uploaded_by.first_name", read_only=True, default="")
    fileSize = serializers.IntegerField(source="file_size", read_only=True)
    # 업로더가 지정한 유형(비면 자동 감지). `profile`은 최종 적용값이다.
    profileHint = serializers.CharField(source="profile_hint", read_only=True)
    profileLabel = serializers.CharField(source="get_profile_display", read_only=True)
    folderId = serializers.IntegerField(source="folder_id", read_only=True)
    folderName = serializers.CharField(source="folder.name", read_only=True, default="")
    # 구판이면 "이전 버전" 배지. 지우지 않는 이유: 과거 판정이 인용한 조항이 사라지면 감사가 끊긴다.
    superseded = serializers.SerializerMethodField()
    # 조 단위 조항 수 / 그중 아직 결정도 룰도 없는 수. 목록·KPI가 이 둘을 쓴다.
    clauseCount = serializers.SerializerMethodField()
    reviewCount = serializers.SerializerMethodField()

    class Meta:
        model = PolicyDoc
        fields = [
            "id", "title", "category", "version", "fileName", "fileSize",
            "profile", "profileHint", "profileLabel", "collection",
            "status", "statusLabel", "chunkCount", "leafCount", "clauseCount", "reviewCount",
            "error", "folderId", "folderName", "superseded",
            "ruleScope", "ruleTrigger", "indexedAt", "uploadedAt", "uploadedBy",
        ]

    def get_fileName(self, obj):
        return obj.file.name.rsplit("/", 1)[-1] if obj.file else ""

    def get_superseded(self, obj):
        return obj.superseded_by_id is not None

    def get_clauseCount(self, obj):
        return obj.clauses.count()

    def get_reviewCount(self, obj):
        """'확인이 필요한 조항' — 룰도 없고 사람 결정도 없는 조항.

        룰 연결은 계산값이라(`PolicyClause.rule_status`) 여기서도 세야 정확하다. 문서
        목록은 문서 수가 많지 않아(관리자가 올리는 규정) 이 비용을 감수한다.
        """
        return sum(1 for c in obj.clauses.all() if c.rule_status() == "NEEDS_REVIEW")


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
