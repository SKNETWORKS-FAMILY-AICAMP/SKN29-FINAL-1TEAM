"""조직/사용자/권한 (기술명세서 §3.1)."""
from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    EMPLOYEE = "EMPLOYEE", "사용자(임직원)"
    TEAM_LEAD = "TEAM_LEAD", "팀장(제출 단위)"
    ACCOUNTANT = "ACCOUNTANT", "회계 담당자"
    ACCOUNTANT_LEAD = "ACCOUNTANT_LEAD", "회계팀장"  # Rule ACTIVE 승인 권한
    EXECUTIVE = "EXECUTIVE", "회계·운영 상부"


class Capability(models.TextChoices):
    """기능 단위 권한 — 역할(Role)과 분리해 개별 부여 가능한 인가 단위.

    실제 인가는 역할 기본값(ROLE_DEFAULT_CAPABILITIES)과 개인 추가부여(User.extra_capabilities)의
    합집합(User.capabilities)으로 판정한다. 역할은 라벨·기본값 산정·화면 rank용으로만 남는다.
    """
    TEAM_AGGREGATE = "team_aggregate", "팀 취합(팀원 건 보완/반려/제출)"
    ACCOUNTING_REVIEW = "accounting_review", "회계 검토·확정"
    RULE_VIEW = "rule_view", "룰 콘솔 열람"
    RULE_ACTIVATE = "rule_activate", "룰 ACTIVE 전환·롤백"
    GOVERNANCE_VIEW = "governance_view", "거버넌스 대시보드 열람"
    AI_LAB = "ai_lab", "AI-LAB(AI 기능 독립 실행) 사용"


# 역할별 기본 부여 능력. 개인 단위로 이 위에 extra_capabilities를 더 얹을 수 있다.
#  룰 콘솔은 회계 공통 열람(rule_view), ACTIVE 전환만 회계팀장(rule_activate)으로 분리.
#  AI-LAB(ai_lab)은 프롬프트·모델 내부가 그대로 보이고 LLM 호출 비용이 나가므로 기본은 회계팀장만.
#  다른 사람에게 필요하면 admin에서 extra_capabilities로 개별 부여한다(슈퍼유저는 항상 보유).
ROLE_DEFAULT_CAPABILITIES = {
    Role.EMPLOYEE: [],
    Role.TEAM_LEAD: [Capability.TEAM_AGGREGATE],
    Role.ACCOUNTANT: [Capability.ACCOUNTING_REVIEW, Capability.RULE_VIEW],
    Role.ACCOUNTANT_LEAD: [
        Capability.ACCOUNTING_REVIEW, Capability.RULE_VIEW, Capability.RULE_ACTIVATE, Capability.AI_LAB,
    ],
    Role.EXECUTIVE: [Capability.GOVERNANCE_VIEW],
}


class OrgCode(models.Model):
    """직급·직책 공통 코드 형태 (마스터 데이터).

    **왜 문서(RAG)가 아니라 DB인가**: 규정 별표는 "직급별 한도"라는 *표*이고, 어떤 사람이
    무슨 직급인지는 *그 사람에 붙은 사실*이다. 후자를 문서에서 뽑으면 세 가지가 깨진다 —
      ① 재현성(FR-RA-08): 같은 정산이 재색인 뒤 다른 판정을 낸다. 조립기(`context_builder`)가
         모든 I/O를 독점하는 이유가 이거다.
      ② 엔티티 매칭: 조직도는 이름을 싣는데, "김민수 → user#3"은 동명이인·퇴사자에서 조용히 틀린다.
      ③ 갱신 주기: 승진할 때마다 PDF를 다시 올려야 직급이 바뀐다.

    ⚠️ **`name`이 별표의 룩업 키다.** `policies/tiger_tables.py`의 `payload`가 이 문자열로
    직접 인덱싱되므로(`{"과장": 300_000}`) 여기 이름과 표의 키가 한 글자라도 다르면
    와일드카드(`"*"`)로 조용히 떨어진다 — 한도가 안 걸리는데 아무 에러도 안 난다.
    """
    code = models.CharField("코드", max_length=32, unique=True)
    name = models.CharField("표기", max_length=32, unique=True, help_text="별표 룩업 키로 그대로 쓰인다.")
    # 상하 비교용. 결재선("과장 이상 승인 필요")은 이름이 아니라 이 값으로 판정해야 한다 —
    # 이름 비교로 만들면 직급 체계가 바뀔 때 룰을 전부 고쳐야 한다.
    rank = models.PositiveSmallIntegerField("서열", help_text="클수록 상위. 결재선 비교에 쓴다.")
    is_active = models.BooleanField("사용", default=True)

    class Meta:
        abstract = True
        ordering = ["rank"]

    def __str__(self):
        return self.name


class JobTitle(OrgCode):
    """직책 — 비직책자·팀장·부서장·본부장·대표이사. **결재권·카드한도의 유일한 축.**

    「직급체계」§1.1: "결재 권한 및 법인카드 사용한도는 **직책** 기준으로 부여한다
    (직급 기준이 아니다)". 별표1의 행이 곧 이 목록이다.

    `Role`(시스템 역할)과 겹쳐 보이지만 다르다: `Role.TEAM_LEAD`는 **이 시스템에서 팀
    취합을 하는 사람**이고(1인 팀 영업사원도 해당된다), 직책 '팀장'은 **조직도상 보임**이다.
    인가는 `Role`/`Capability`가, 결재선·한도표 축은 이쪽이 담당한다.
    """

    class Meta(OrgCode.Meta):
        abstract = False
        verbose_name = verbose_name_plural = "직책"


class Position(OrgCode):
    """직급 — 사원~대표이사 10단계. **처우(급여·승진) 기준이며 판정에 쓰지 않는다.**

    「직급체계」§1.2. 판정 축으로 쓰면 규정과 정반대가 된다 — 같은 '이사'라도 부서장
    겸직이냐 본부장 대행이냐로 한도가 갈리므로(별표1 각주) 직급으로는 한도를 정할 수 없다.
    그래서 `EvalContext`에 올리지 않는다. 화면 표기·인사 정보 용도다.
    """
    # 직급표(「직급체계」§2)의 "보임 가능 직책". **강제 제약이 아니라 경고용**이다 —
    # 발령이 규정을 앞서는 실무가 있고, DB로 막으면 그런 건을 기록조차 못 하게 된다.
    assignable_titles = models.JSONField("보임 가능 직책", default=list, blank=True)

    class Meta(OrgCode.Meta):
        abstract = False
        verbose_name = verbose_name_plural = "직급"


class Team(models.Model):
    """제출 단위(조직도 팀이 아니라 정산을 취합해 올리는 단위, 1인도 가능)."""
    name = models.CharField(max_length=100)
    bu = models.CharField("본부", max_length=100, blank=True)
    is_submission_unit = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class User(AbstractUser):
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.EMPLOYEE)
    team = models.ForeignKey(
        Team, null=True, blank=True, on_delete=models.SET_NULL, related_name="members"
    )
    # 역할 기본 능력 외에 개인 단위로 추가 부여하는 기능 권한(Capability 값 리스트).
    extra_capabilities = models.JSONField(default=list, blank=True)
    # 직책 — **판정이 쓰는 사실**이라 모르면 `None`으로 둔다(지어내면 그대로 오판이 된다).
    #  미지정이면 별표가 와일드카드(`"*"`) 기본값으로 해소된다(`PolicyTable.strict_keys=False`).
    job_title = models.ForeignKey(
        JobTitle, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="users", verbose_name="직책",
        help_text="결재권·카드한도의 기준. 규정상 발령일부터 적용된다.",
    )
    # 직급 — 처우 축. 판정에 쓰지 않으므로 EvalContext에 올라가지 않는다.
    position = models.ForeignKey(
        Position, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="users", verbose_name="직급",
        help_text="급여·승진 등 처우 기준(표시용). 한도·결재권 판정에는 쓰이지 않는다.",
    )

    @property
    def capabilities(self) -> list:
        """유효 기능 권한 = 역할 기본 ∪ 개인 추가부여. (슈퍼유저는 전체 능력)"""
        if self.is_superuser:
            return [c.value for c in Capability]
        caps = {c.value for c in ROLE_DEFAULT_CAPABILITIES.get(self.role, [])}
        caps |= {str(c) for c in (self.extra_capabilities or [])}
        return sorted(caps)

    def has_capability(self, cap) -> bool:
        """cap(Capability 또는 값 문자열)을 보유했는지."""
        return bool(self.is_superuser or str(cap) in self.capabilities)

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"
