"""사용자 조회 헬퍼 — **기능 권한(Capability) 기준**.

## 왜 DB 필터로 안 되나

유효 능력은 `역할 기본값 ∪ 개인 추가부여`이고 후자가 `JSONField`라, `capability='x'`를
SQL로 거를 수 없다(`User.capabilities`는 Python property다). 그래서 후보를 좁혀 받아온 뒤
Python에서 거른다 — 사용자 수가 수백 규모라 문제되지 않는다.

**역할로 대신 거르지 않는다.** 인가의 정본은 Capability이고(기술 §3.1a), 개인 추가부여
(`extra_capabilities`)로만 능력을 가진 사람이 실재한다 — 역할로 거르면 그 사람이 빠진다.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model


def users_with_capability(capability, *, team=None, exclude=None):
    """해당 능력을 가진 **활성** 사용자 목록.

    Args:
        capability: `Capability` 또는 그 값 문자열.
        team: 주면 그 팀 소속으로 한정(팀 취합처럼 팀 단위인 알림).
        exclude: 제외할 사용자(대개 그 일을 일으킨 본인).
    """
    User = get_user_model()
    qs = User.objects.filter(is_active=True)
    if team is not None:
        qs = qs.filter(team=team)
    if exclude is not None and getattr(exclude, "pk", None):
        qs = qs.exclude(pk=exclude.pk)
    #  슈퍼유저는 `capabilities`가 전체라 자동으로 포함된다 — 관리자에게도 알림이 간다.
    return [u for u in qs.select_related("team") if u.has_capability(capability)]
