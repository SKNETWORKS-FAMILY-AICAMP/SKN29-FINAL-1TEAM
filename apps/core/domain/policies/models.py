"""규정 + 룰 그래프 도메인 (기술명세서 §3.1, §4.2).

룰 도메인 = 그래프(트리):
- RuleGraph(최종 상태 도메인): 단건 룰(노드)들이 트리/DAG로 조립된 배포 단위.
  ACTIVE·버전관리·시뮬레이션·롤백은 모두 이 그래프 단위.
- RuleNode(룰 노드): condition + action.
- RuleRouting(next_routings): 평가 결과별 다음 노드 라우팅.
- 엔진: ACTIVE 그래프를 엔트리부터 순회 → 단말 결정, 경로를 RuleHit.path에 기록.
"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from domain.settlements.models import Category


RULE_SCOPE_CHOICES = [("GLOBAL", "공통 필수 게이트"), *Category.choices]


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


class PolicyTable(models.Model):
    """규정 별표(임계값 표) 원본 1개 = 1행 — `_context/policy-domain.md` §2.

    별표마다 축 개수·깊이가 다르다(직책 1키 / 출장구분×지역등급 2키 / 축 없는 전역값).
    고정 컬럼으로는 담을 수 없으므로 표 원문 구조를 ``payload``에 그대로 두고, 룩업 축만
    ``key_axes``에 **EvalContext 경로**로 선언한다. 조립기는 이 선언만 보고 룩업하므로
    축이 2개든 3개든 코드 변경이 없다(마이그레이션 0).

    **개정은 UPDATE가 아니라 INSERT**: 새 ``effective_date`` 행을 추가하고 구행에
    ``superseded_date``를 찍는다. 과거 판정을 그 시점 한도로 재현하기 위해서다.
    """
    key = models.CharField(max_length=64, db_index=True)          # 'lodging_limit_table'
    title = models.CharField(max_length=200, blank=True)          # '별표2. 지역등급별 숙박비 한도'
    key_axes = models.JSONField(default=list, blank=True)         # ["trip.trip_type","trip.region_grade"]
    # 축을 모두 따라간 리프는 스칼라. 축이 없으면 {"value": <스칼라>}.
    # 표에 없는 키 값은 "*"(와일드카드) 항목으로 폴백한다.
    payload = models.JSONField(default=dict, blank=True)
    strict_keys = models.BooleanField(
        "키 미상 시 해소 금지", default=False,
        help_text=(
            "False(기본): 축 값을 몰라도 '*' 기본값으로 해소한다 — 회사 기본 한도처럼 "
            "기본값이 의미 있는 표.\n"
            "True: 축 값을 모르면 해소하지 않고 null로 남긴다 — 금지업종처럼 "
            "'모르면 안전하다'고 단정할 수 없는 표. null이면 미해소 가드가 REVIEW로 강등한다."
        ),
    )
    source_doc = models.ForeignKey(
        PolicyDoc, null=True, blank=True, on_delete=models.SET_NULL, related_name="tables",
    )
    source_clause = models.CharField(max_length=200, blank=True)  # 'TIGER-REG-2026-003 별표2'
    effective_date = models.DateField()
    superseded_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["key", "-effective_date"]
        constraints = [
            models.UniqueConstraint(fields=["key", "effective_date"], name="uq_policy_table_key_effective"),
        ]
        indexes = [models.Index(fields=["key", "effective_date"], name="ix_policy_table_lookup")]

    def __str__(self):
        return f"{self.key}@{self.effective_date}"


class RuleGraphStatus(models.TextChoices):
    DRAFT = "DRAFT", "초안"
    SIMULATED = "SIMULATED", "시뮬레이션"
    ACTIVE = "ACTIVE", "활성"
    ARCHIVED = "ARCHIVED", "보관"


class RuleGraph(models.Model):
    """룰 그래프의 한 버전. 같은 ``family_key`` 행들이 버전 계열을 이룬다."""
    family_key = models.UUIDField(default=uuid.uuid4, db_index=True)
    name = models.CharField(max_length=150)
    scope = models.CharField(max_length=20, choices=RULE_SCOPE_CHOICES, default="GLOBAL")
    status = models.CharField(max_length=12, choices=RuleGraphStatus.choices, default=RuleGraphStatus.DRAFT)
    version = models.PositiveIntegerField(default=1)
    entry_node_key = models.CharField(max_length=64, blank=True)
    sim_result = models.JSONField(default=dict, blank=True)  # 최신 시뮬레이션 요약(통계·등급) 캐시
    source_clause = models.CharField(max_length=200, blank=True)
    # 검토자(Active 요청자) 추적 — 시뮬레이션 보고서를 확인하고 활성화를 요청한 사람.
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="reviewed_graphs",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_comment = models.TextField(blank=True)  # 검토자 코멘트(보고서 형식, 마크다운)
    # 활성자 추적 — 실제 ACTIVE 전환을 실행한 사람.
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_graphs")
    activated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["family_key", "version"], name="uq_rulegraph_family_version"),
            models.UniqueConstraint(
                fields=["scope"], condition=Q(status=RuleGraphStatus.ACTIVE),
                name="uq_rulegraph_active_scope",
            ),
            models.CheckConstraint(
                condition=Q(scope__in=["GLOBAL", *Category.values]),
                name="ck_rulegraph_scope",
            ),
        ]

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
        constraints = [
            models.UniqueConstraint(fields=["graph", "version"], name="uq_graph_snapshot_version"),
            models.UniqueConstraint(
                fields=["graph"], condition=Q(is_active=True), name="uq_graph_active_snapshot"
            ),
        ]


class RuleNode(models.Model):
    """단건 룰(노드): condition + action."""
    graph = models.ForeignKey(RuleGraph, on_delete=models.CASCADE, related_name="nodes")
    node_key = models.CharField(max_length=64)
    condition = models.JSONField(default=dict, blank=True)  # DSL/JSON
    action = models.JSONField(default=dict, blank=True)     # {decision: PASS/REJECT/REVIEW, ...}
    # "이 Rule이 하는 일" — 비개발자용 설명 문장. Rule Agent가 조건·액션을 만들 때 함께 생성해 저장한다.
    # 프론트에서 DSL을 파싱해 만들지 않고 이 값을 그대로 노출한다(비면 프론트의 기계 번역으로 폴백).
    condition_text = models.TextField(blank=True)
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
        constraints = [
            models.UniqueConstraint(
                fields=["graph", "from_node_key", "on_result", "priority"],
                name="uq_rule_routing_priority",
            )
        ]


class RuleTestCase(models.Model):
    """검증 시뮬레이션용 커스텀 테스트케이스 — 어느 그래프 **버전**의 검증셋인지로 소유된다.

    버전 복제(create_draft_version) 시 함께 복제되어, 각 버전이 자기 검증셋을 갖는다.
    """
    graph = models.ForeignKey(RuleGraph, on_delete=models.CASCADE, related_name="test_cases")
    key = models.CharField(max_length=32)  # 화면에서 쓰는 TC-1 같은 식별자(그래프 내 유일)
    label = models.CharField(max_length=120, blank=True)
    merchant = models.CharField(max_length=200, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    category = models.CharField(max_length=20, blank=True)
    merchant_type = models.CharField(max_length=100, blank=True)
    payment_method = models.CharField(max_length=30, blank=True)
    expected = models.CharField(max_length=12, blank=True)  # 기대 판정. 비면 채점하지 않는다.
    facts = models.JSONField(default=dict, blank=True)      # EvalContext dot-path → 값
    order = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("graph", "key")
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.graph_id}:{self.key}"


class RuleAuthoringMessage(models.Model):
    """룰 초안 작성 대화 로그 — 회계 담당자 지시와 Rule Agent의 반영 결과.

    "누가 무엇을 지시했고, Agent가 그래프의 어느 필드를 어떻게 바꿨는지"를 남겨
    비개발자가 만든 룰도 변경 이력을 추적할 수 있게 한다.
    """
    class Role(models.TextChoices):
        USER = "user", "사용자"
        AI = "ai", "Rule Agent"

    graph = models.ForeignKey(RuleGraph, on_delete=models.CASCADE, related_name="messages")
    node_key = models.CharField(max_length=64, blank=True)  # 비면 그래프 전체 대상 지시
    role = models.CharField(max_length=8, choices=Role.choices)
    text = models.TextField()
    applied_note = models.CharField(max_length=200, blank=True)  # "조건·액션에 적용됨" 같은 반영 요약
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]


class SimulationSource(models.TextChoices):
    TEST = "TEST", "검증셋"
    HISTORY = "HISTORY", "실제 내역"


class RuleSimulationRun(models.Model):
    """검증 시뮬레이션 1회 실행 = 보고서 1건.

    "어떤 그래프의 어떤 버전을, 어떤 구조 스냅샷 상태에서" 돌렸는지까지 보존한다.
    화면에는 최신 실행만 보여주되, 스냅샷 해시가 현재 그래프와 다르면 낡은 결과로 표시한다.
    """
    graph = models.ForeignKey(RuleGraph, on_delete=models.CASCADE, related_name="simulation_runs")
    graph_version = models.PositiveIntegerField(default=1)
    snapshot = models.JSONField(default=dict, blank=True)   # 실행 시점 노드·라우팅·entry
    snapshot_hash = models.CharField(max_length=64, db_index=True)
    period_label = models.CharField(max_length=40, blank=True)
    structure_error = models.CharField(max_length=300, blank=True)
    stats = models.JSONField(default=dict, blank=True)
    grades = models.JSONField(default=dict, blank=True)
    agent_report = models.TextField(blank=True)
    ran_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    ran_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-ran_at", "-id"]

    def __str__(self):
        return f"Sim#{self.pk} {self.graph_id} v{self.graph_version}"


class RuleSimulationResult(models.Model):
    """시뮬레이션 실행의 개별 판정 결과 행(검증셋 케이스 또는 실제 정산 내역)."""
    run = models.ForeignKey(RuleSimulationRun, on_delete=models.CASCADE, related_name="results")
    source = models.CharField(max_length=8, choices=SimulationSource.choices)
    test_case = models.ForeignKey(
        RuleTestCase, null=True, blank=True, on_delete=models.SET_NULL, related_name="results",
    )
    settlement = models.ForeignKey(
        "settlements.Settlement", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    row_key = models.CharField(max_length=64)
    label = models.CharField(max_length=200, blank=True)
    merchant = models.CharField(max_length=200, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    category = models.CharField(max_length=20, blank=True)
    date_label = models.CharField(max_length=16, blank=True)
    current_status = models.CharField(max_length=24, blank=True)
    baseline = models.CharField(max_length=12, blank=True)   # 기존 분류(정산 상태 환산)
    decision = models.CharField(max_length=12, blank=True)   # 그래프 판정
    path = models.JSONField(default=list, blank=True)
    flags = models.JSONField(default=list, blank=True)
    expected = models.CharField(max_length=12, blank=True)
    matched_expectation = models.BooleanField(null=True, blank=True)
    changed = models.BooleanField(default=False)
    risk = models.BooleanField(default=False)
    auto = models.BooleanField(default=False)
    ai_comment = models.TextField(blank=True)
    comment_verdict = models.CharField(max_length=12, blank=True)  # intended | risk
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]


class RuleHit(models.Model):
    """Rule 판정 로그 — 판정 입력 전체를 보존해 재현·감사를 지원."""
    transaction = models.ForeignKey("transactions.Transaction", null=True, blank=True, on_delete=models.SET_NULL)
    settlement = models.ForeignKey("settlements.Settlement", null=True, blank=True, on_delete=models.SET_NULL, related_name="rule_hits")
    graph = models.ForeignKey(RuleGraph, null=True, blank=True, on_delete=models.SET_NULL)
    graph_version = models.PositiveIntegerField(default=0)
    path = models.JSONField(default=list, blank=True)  # 방문 노드 순서
    eval_context = models.JSONField(default=dict, blank=True)  # 판정 시점 facts 스냅샷
    flags = models.JSONField(default=list, blank=True)  # 매칭 노드의 사유 플래그
    eval_context_schema_version = models.PositiveIntegerField(default=1)
    builder_version = models.CharField(max_length=20, blank=True)
    decision = models.CharField(max_length=12, blank=True)
    confidence = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)
