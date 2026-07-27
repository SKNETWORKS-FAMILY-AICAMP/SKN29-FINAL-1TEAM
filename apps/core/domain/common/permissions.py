"""역할 기반 권한 (요구사항 RBAC).

- 검토(승인/보완/반려)·확정: 회계 담당자(ACCOUNTANT/ACCOUNTANT_LEAD)
- Rule ACTIVE 승인/롤백: 회계팀장(ACCOUNTANT_LEAD)
슈퍼유저는 항상 허용(관리·테스트 편의).
"""
from rest_framework.permissions import BasePermission


def _role(request):
    u = getattr(request, "user", None)
    if not (u and u.is_authenticated):
        return None
    return getattr(u, "role", None)


class IsAccountant(BasePermission):
    message = "회계 담당자 권한이 필요합니다."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and (u.is_superuser or _role(request) in ("ACCOUNTANT", "ACCOUNTANT_LEAD")))


class IsAccountantLead(BasePermission):
    message = "회계팀장(Rule 승인) 권한이 필요합니다."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and (u.is_superuser or _role(request) == "ACCOUNTANT_LEAD"))
