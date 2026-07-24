"""규정 + 룰 그래프 도메인 (기술명세서 §3.1, §4.2).

룰 도메인 = 그래프(트리):
- RuleGraph(최종 상태 도메인): 단건 룰(노드)들이 트리/DAG로 조립된 배포 단위.
  ACTIVE·버전관리·시뮬레이션·롤백은 모두 이 그래프 단위.
- RuleNode(룰 노드): condition + action.
- RuleRouting(next_routings): 평가 결과별 다음 노드 라우팅.
- 엔진: ACTIVE 그래프를 엔트리부터 순회 → 단말 결정, 경로를 RuleHit.path에 기록.
"""
from django.conf import settings
from django.db import models


class Policy(models.Model):
    category = models.CharField(max_length=20)
    limit_amount = models.DecimalField(max_digits=12, decimal_places=0, null=True, blank=True)
    required_evidence = models.JSONField(default=list, blank=True)
    tax_note = models.TextField(blank=True)
    refs = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name_plural = "policies"

    def __str__(self):
        return f"Policy({self.category})"


class PolicyDoc(models.Model):
    """RAG 소스 규정 문서 메타. 실제 임베딩(Chroma)은 ai(FastAPI)가 수행."""
    title = models.CharField(max_length=200)
    category = models.CharField(max_length=20, blank=True)
    version = models.CharField(max_length=20, blank=True)
    effective_date = models.DateField(null=True, blank=True)
    file_ref = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class RuleGraphStatus(models.TextChoices):
    DRAFT = "DRAFT", "초안"
    SIMULATED = "SIMULATED", "시뮬레이션"
    ACTIVE = "ACTIVE", "활성"
    ARCHIVED = "ARCHIVED", "보관"


class RuleGraph(models.Model):
    """룰 그래프 = 최종 상태 도메인. ACTIVE·버전·롤백 단위."""
    name = models.CharField(max_length=150)
    scope = models.CharField(max_length=50, default="GLOBAL")  # 전사/분류/본부
    status = models.CharField(max_length=12, choices=RuleGraphStatus.choices, default=RuleGraphStatus.DRAFT)
    version = models.PositiveIntegerField(default=1)
    entry_node_key = models.CharField(max_length=64, blank=True)
    sim_result = models.JSONField(default=dict, blank=True)  # 매칭/오탐율/검토감소량/노드 커버리지
    source_clause = models.CharField(max_length=200, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_graphs")
    activated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} v{self.version} ({self.status})"


class RuleGraphVersion(models.Model):
    """그래프 버전 스냅샷 — 버전관리·롤백 단위."""
    graph = models.ForeignKey(RuleGraph, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    snapshot = models.JSONField(default=dict, blank=True)  # 노드+라우팅 스냅샷
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    approved_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=False)

    class Meta:
        ordering = ["-version"]
        unique_together = ("graph", "version")


class RuleNode(models.Model):
    """단건 룰(노드): condition + action."""
    graph = models.ForeignKey(RuleGraph, on_delete=models.CASCADE, related_name="nodes")
    node_key = models.CharField(max_length=64)
    condition = models.JSONField(default=dict, blank=True)  # DSL/JSON
    action = models.JSONField(default=dict, blank=True)     # {decision: PASS/REJECT/REVIEW, ...}
    priority = models.IntegerField(default=0)

    class Meta:
        unique_together = ("graph", "node_key")
        ordering = ["priority"]

    def __str__(self):
        return f"{self.graph_id}:{self.node_key}"


class OnResult(models.TextChoices):
    MATCH = "MATCH", "일치"
    NO_MATCH = "NO_MATCH", "불일치"
    PASS = "PASS", "통과"
    REJECT = "REJECT", "반려"
    REVIEW = "REVIEW", "검토"


class RuleRouting(models.Model):
    """next_routings: 평가 결과별 다음 노드 방향(우선순위 포함)."""
    graph = models.ForeignKey(RuleGraph, on_delete=models.CASCADE, related_name="routings")
    from_node_key = models.CharField(max_length=64)
    on_result = models.CharField(max_length=10, choices=OnResult.choices)
    to_node_key = models.CharField(max_length=64, blank=True)  # 비면 단말
    priority = models.IntegerField(default=0)

    class Meta:
        ordering = ["priority"]


class RuleHit(models.Model):
    """Rule 판정 로그 — 순회 경로(path)·그래프 버전 포함."""
    transaction = models.ForeignKey("transactions.Transaction", null=True, blank=True, on_delete=models.SET_NULL)
    settlement = models.ForeignKey("settlements.Settlement", null=True, blank=True, on_delete=models.SET_NULL, related_name="rule_hits")
    graph = models.ForeignKey(RuleGraph, null=True, blank=True, on_delete=models.SET_NULL)
    graph_version = models.PositiveIntegerField(default=0)
    path = models.JSONField(default=list, blank=True)  # 방문 노드 순서
    decision = models.CharField(max_length=12, blank=True)
    confidence = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)
