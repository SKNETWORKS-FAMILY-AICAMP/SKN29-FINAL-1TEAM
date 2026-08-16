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


class IngestStatus(models.TextChoices):
    """규정 문서 적재 진행 상태.

    `PENDING`과 `FAILED`를 구분하는 이유: 파싱은 문서당 수십 초가 걸려서 "아직 도는 중"과
    "실패했다"를 화면이 가려낼 수 있어야 재색인 버튼을 언제 눌러야 할지 판단할 수 있다.
    """
    PENDING = "PENDING", "대기"
    PARSING = "PARSING", "파싱·청킹 중"
    INDEXING = "INDEXING", "임베딩·적재 중"
    DONE = "DONE", "적재 완료"
    FAILED = "FAILED", "실패"


class PolicyFolder(models.Model):
    """규정 문서 정리용 폴더(트리).

    벡터 검색에는 아무 영향이 없다 — 순전히 **사람이 문서를 찾기 위한** 분류다. 그래서
    컬렉션 라우팅(프로파일이 결정)과 섞지 않는다. 폴더를 지워도 문서는 남는다(미분류로).
    """
    name = models.CharField(max_length=80)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children",
    )
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["parent", "name"], name="uq_policyfolder_parent_name",
            ),
        ]

    def __str__(self):
        return self.name


class PolicyDoc(models.Model):
    """RAG 소스 규정 문서 — 원본 파일 + 적재 결과 메타.

    **원본 파일은 Django(SoR)가 갖고, 벡터는 Chroma가 갖는다.** 적재(파싱→청킹→임베딩→upsert)는
    ai(FastAPI)가 수행하고 결과만 여기로 돌려준다 — FastAPI는 Postgres에 직접 접근하지
    않는다(기술명세서 §5.1). 진행 상태를 여기 두는 이유는 화면이 폴링할 곳이 필요해서다.
    """
    title = models.CharField(max_length=200)
    category = models.CharField(max_length=20, blank=True)
    version = models.CharField(max_length=20, blank=True)
    effective_date = models.DateField(null=True, blank=True)
    # 업로드 원본. ai 컨테이너는 같은 media 볼륨을 읽기전용으로 마운트해 이 경로를 연다
    # (docling이 파일 경로를 요구하고, 바이트를 HTTP로 되넘기는 것보다 싸다).
    file = models.FileField("원본 파일", upload_to="policy_docs/%Y%m/", blank=True)
    file_size = models.PositiveIntegerField("원본 크기(byte)", default=0)
    folder = models.ForeignKey(
        PolicyFolder, null=True, blank=True, on_delete=models.SET_NULL, related_name="documents",
    )
    # 개정으로 대체된 구판. null이면 현행본이다 — 화면의 "이전 버전" 배지가 이 값을 본다.
    # 구판도 지우지 않는 이유: 과거 판정이 인용한 조항이 사라지면 감사 추적이 끊긴다.
    superseded_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="supersedes",
    )

    # ── 적재 결과 (ai가 콜백으로 채운다) ─────────────────────────
    status = models.CharField(max_length=12, choices=IngestStatus.choices, default=IngestStatus.PENDING)
    # 파일 내용 해시(파서가 계산). 같은 파일이면 같은 값이라 재적재가 멱등 upsert가 된다.
    doc_id = models.CharField(max_length=32, blank=True, db_index=True)
    profile = models.CharField("문서 유형", max_length=16, blank=True)  # REGULATION/LAW/DIAGRAM/GENERIC
    collection = models.CharField(max_length=32, blank=True)           # policy_docs/tax_refs/org_docs
    chunk_count = models.PositiveIntegerField(default=0)
    leaf_count = models.PositiveIntegerField(default=0)   # 검색 대상(부모 제외) 청크 수
    error = models.TextField(blank=True)                  # 실패 사유 — 감추지 않는다
    indexed_at = models.DateTimeField(null=True, blank=True)

    # 적재 완료 후 룰 생성 트리거 결과. 아직 자동 생성을 켜지 않아 "개발 중" 응답이 들어온다.
    rule_trigger = models.JSONField(default=dict, blank=True)
    # 트리거 대상 비용분류(GLOBAL ∪ Category). 비면 문서에서 정하지 못한 것.
    rule_scope = models.CharField(max_length=20, blank=True)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="uploaded_policy_docs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.title


class ClauseDecision(models.TextChoices):
    """조항에 대한 **사람의 결정**. 룰 연결 여부(파생)와 다른 축이다."""
    NONE = "", "미결정"
    SKIP = "SKIP", "규칙 생성 안 함"


class PolicyClause(models.Model):
    """규정 문서의 조(條) 하나 — 화면이 보여주고 사람이 결정을 내리는 단위.

    **왜 Postgres에도 두는가**: 조항 본문은 Chroma에도 있지만 그건 *검색용 사본*이다.
    조항은 판정이 인용하는 근거이자 **사람이 "이건 규칙으로 만들지 않겠다"고 결정하는
    대상**이라, 그 결정을 붙일 자리가 SoR에 있어야 한다(CLAUDE.md §1 — SoR은 Postgres 하나).

    **상태를 저장하지 않는 이유**: "규칙 연결됨/확인 필요/생성 안 함"은 셋 중 둘이 파생이다.
    룰은 나중에 생기고 나중에 지워지므로, 상태를 컬럼에 굳히면 곧 실제와 어긋난다.
    저장하는 건 사람의 결정(`decision`)뿐이고 나머지는 `rule_status()`가 그때그때 계산한다.
    """
    doc = models.ForeignKey(PolicyDoc, on_delete=models.CASCADE, related_name="clauses")
    order = models.PositiveIntegerField(default=0)
    article_no = models.PositiveIntegerField(null=True, blank=True)
    article_label = models.CharField("조 라벨", max_length=32, blank=True)   # "제9조" / "제55조의2"
    article_title = models.CharField(max_length=200, blank=True)             # "(사용 한도)"
    # 인용 문자열("법인카드_사용규정 제9조"). 룰 노드의 action.source_clause와 맞춰 연결을 찾는다.
    citation = models.CharField(max_length=300, blank=True, db_index=True)
    body = models.TextField("원문(Markdown)", blank=True)
    page_start = models.PositiveIntegerField(default=0)
    page_end = models.PositiveIntegerField(default=0)
    chunk_ids = models.JSONField(default=list, blank=True)   # 이 조항을 이루는 Chroma 청크

    # ── 사람의 결정 ─────────────────────────────────────────────
    decision = models.CharField(max_length=8, choices=ClauseDecision.choices, blank=True, default="")
    decision_reason = models.TextField("결정 사유", blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="decided_clauses",
    )
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["doc", "article_label"], name="uq_clause_doc_article"),
        ]

    def __str__(self):
        return f"{self.doc.title} {self.article_label}"

    def linked_nodes(self):
        """이 조항을 근거로 만들어진 룰 노드 — `action.source_clause` 일치로 찾는다.

        문자열 매칭인 이유: 룰 노드는 Agent가 만들 수도 사람이 만들 수도 있고, 조항 행이
        생기기 전에 만들어졌을 수도 있다. FK로 묶으면 그 경우들이 전부 예외가 된다.
        """
        if not self.citation:
            return RuleNode.objects.none()
        return RuleNode.objects.filter(action__source_clause=self.citation).select_related("graph")

    def rule_status(self, linked_count: int | None = None) -> str:
        """LINKED / SKIPPED / NEEDS_REVIEW — 저장하지 않고 계산한다.

        `linked_count`를 받는 이유는 목록 조회에서 N+1을 피하기 위해서다(호출부가 한 번에
        세어 넘긴다). 없으면 여기서 직접 센다.
        """
        count = self.linked_nodes().count() if linked_count is None else linked_count
        if count:
            return "LINKED"
        if self.decision == ClauseDecision.SKIP:
            return "SKIPPED"
        return "NEEDS_REVIEW"


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
    # Rule Agent가 이 그래프를 만든 근거 — 모델·질의·검색 출처(citation)·탈락 노드.
    # 노드별 출처는 action.source_clause에 있지만 **그래프 단위** 생성 이력은 여기 남는다.
    # 사람이 직접 만든 그래프는 빈 dict(= AI 생성물이 아님).
    generation_meta = models.JSONField(default=dict, blank=True)
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
                # "TEST_DEMO"는 실제 비용분류가 아니다 — seed_rules.py TEST 픽스처(구조 검증용,
                # "규정 근거 없음") 전용 sentinel. RULE_SCOPE_CHOICES/scope.normalize_scope에는
                # 없으므로 create_graph_draft() 등 일반 생성 경로로는 만들 수 없고(앱 레벨에서
                # 걸림), 오직 seed 스크립트의 직접 ORM 조작으로만 존재한다 — 그래도 여기서
                # 명시적으로 허용해두지 않으면 이 DB 제약 자체가 그 시드를 막는다.
                condition=Q(scope__in=["GLOBAL", "TEST_DEMO", *Category.values]),
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
