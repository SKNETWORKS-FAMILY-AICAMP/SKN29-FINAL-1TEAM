"""기능 단위(Capability) 권한 — 역할과 분리된 인가.

인가는 User.has_capability(Capability.*)로 판정한다(역할 기본 ∪ 개인 추가부여).
슈퍼유저는 항상 허용(관리·테스트 편의).

- 팀 취합(팀원 건 보완/반려/제출): CanTeamAggregate
- 회계 검토(승인/보완/반려)·확정: CanAccountingReview
- Rule ACTIVE 전환/롤백: CanActivateRule
- 거버넌스 대시보드 열람: CanViewGovernance
- AI-LAB(AI 기능 독립 실행): CanUseAiLab
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


class CanViewRule(HasCapability):
    """룰 콘솔 조회와 DRAFT 작성 권한."""
    capability = Capability.RULE_VIEW
    message = "룰 콘솔 권한이 필요합니다."


class CanViewGovernance(HasCapability):
    capability = Capability.GOVERNANCE_VIEW
    message = "거버넌스 대시보드 열람 권한이 필요합니다."


class CanUseAiLab(HasCapability):
    """AI-LAB(AI 기능 독립 실행) 사용 — 프롬프트·모델 내부 노출 + LLM 호출 비용 발생."""
    capability = Capability.AI_LAB
    message = "AI-LAB 사용 권한이 필요합니다."


# ── 하위호환 별칭(구 역할기반 이름) — 신규 코드는 위 Capability 클래스를 쓸 것 ──
IsAccountant = CanAccountingReview
IsAccountantLead = CanActivateRule


class CanAccountingReviewOrGovernance(BasePermission):
    """회계 검토 **또는** 거버넌스 열람 — 예산 관리 화면처럼 두 역할이 함께 보는 자리.

    `HasCapability`는 단일 capability만 본다. 여기에 억지로 끼우지 않고 별도 클래스를
    두는 이유: 다중 조건을 베이스에 넣으면 모든 권한이 목록을 갖게 되고, "이 화면은
    무슨 권한인가"를 한 줄로 읽을 수 없게 된다.
    """
    message = "회계 검토 또는 거버넌스 열람 권한이 필요합니다."
    capabilities = (Capability.ACCOUNTING_REVIEW, Capability.GOVERNANCE_VIEW)

    def has_permission(self, request, view):
        u = getattr(request, "user", None)
        if not (u and u.is_authenticated):
            return False
        return any(u.has_capability(c) for c in self.capabilities)
