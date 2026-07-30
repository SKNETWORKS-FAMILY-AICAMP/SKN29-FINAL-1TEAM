"""기능 단위(Capability) 권한 — 역할과 분리된 인가.

인가는 User.has_capability(Capability.*)로 판정한다(역할 기본 ∪ 개인 추가부여).
슈퍼유저는 항상 허용(관리·테스트 편의).

- 팀 취합(팀원 건 보완/반려/제출): CanTeamAggregate
- 회계 검토(승인/보완/반려)·확정: CanAccountingReview
- Rule ACTIVE 전환/롤백: CanActivateRule
- 거버넌스 대시보드 열람: CanViewGovernance
"""
from rest_framework.permissions import BasePermission

from domain.accounts.models import Capability


class HasCapability(BasePermission):
    """capability(Capability 값)를 보유한 인증 사용자만 허용하는 베이스 클래스."""
    capability = None
    message = "필요한 기능 권한이 없습니다."

    def has_permission(self, request, view):
        u = getattr(request, "user", None)
        return bool(u and u.is_authenticated and self.capability and u.has_capability(self.capability))


class CanTeamAggregate(HasCapability):
    capability = Capability.TEAM_AGGREGATE
    message = "팀 취합 권한이 필요합니다."


class CanAccountingReview(HasCapability):
    capability = Capability.ACCOUNTING_REVIEW
    message = "회계 검토·확정 권한이 필요합니다."


class CanActivateRule(HasCapability):
    capability = Capability.RULE_ACTIVATE
    message = "룰 활성 전환 권한이 필요합니다."


class CanViewGovernance(HasCapability):
    capability = Capability.GOVERNANCE_VIEW
    message = "거버넌스 대시보드 열람 권한이 필요합니다."


# ── 하위호환 별칭(구 역할기반 이름) — 신규 코드는 위 Capability 클래스를 쓸 것 ──
IsAccountant = CanAccountingReview
IsAccountantLead = CanActivateRule
