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


# 역할별 기본 부여 능력. 개인 단위로 이 위에 extra_capabilities를 더 얹을 수 있다.
#  룰 콘솔은 회계 공통 열람(rule_view), ACTIVE 전환만 회계팀장(rule_activate)으로 분리.
ROLE_DEFAULT_CAPABILITIES = {
    Role.EMPLOYEE: [],
    Role.TEAM_LEAD: [Capability.TEAM_AGGREGATE],
    Role.ACCOUNTANT: [Capability.ACCOUNTING_REVIEW, Capability.RULE_VIEW],
    Role.ACCOUNTANT_LEAD: [Capability.ACCOUNTING_REVIEW, Capability.RULE_VIEW, Capability.RULE_ACTIVATE],
    Role.EXECUTIVE: [Capability.GOVERNANCE_VIEW],
}


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
