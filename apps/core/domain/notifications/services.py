"""알림 생성 — **모든 알림은 이 모듈을 거친다.**

호출부마다 `Notification.objects.create()`를 하면 링크·제목 규칙이 곧 갈리고, 어느 하나는
반드시 빠진다(`risk_review`가 `judge` 액션에만 있어서 제출 경로에서 통째로 안 돌던 것과 같다).

## 지키는 규칙 4개

1. **본인이 한 일은 본인에게 알리지 않는다** — `actor == recipient`면 만들지 않는다.
   내가 누른 버튼의 결과를 알림으로 받으면 소음이다.
2. **알림 실패가 업무를 막지 않는다** — 수신자 조회·저장이 실패해도 예외를 올리지 않는다.
   상태 전이가 알림 때문에 롤백되면 안 된다.
3. **링크는 종류에서 파생**한다(`LINK_OF`). 호출부가 경로를 적지 않는다.
4. **개수형 알림은 묶는다** — 미읽음 상태의 같은 `dedupe_key`가 있으면 `count`를 올린다.
"""
from __future__ import annotations

import logging

from django.db import models

from .models import COALESCING_KINDS, LINK_OF, Notification, NotificationKind

logger = logging.getLogger(__name__)


def notify(recipient, kind, *, title, body="", target="", actor=None,
           dedupe_key="") -> Notification | None:
    """알림 한 건. 만들지 않은 경우(본인·수신자 없음·오류)는 `None`."""
    if recipient is None:
        return None
    if actor is not None and getattr(actor, "pk", None) == recipient.pk:
        return None  # 규칙 1

    try:
        link = LINK_OF[kind]
        if kind in COALESCING_KINDS and dedupe_key:
            existing = (
                Notification.objects
                .filter(recipient=recipient, kind=kind, dedupe_key=dedupe_key, read_at__isnull=True)
                .first()
            )
            if existing is not None:
                #  읽지 않은 같은 알림이 있으면 개수만 올린다. 제목은 최신 문구로 바꾼다
                #  (「3건」 → 「4건」). 읽은 뒤에 온 건은 새 행이다 — 다시 알려야 한다.
                Notification.objects.filter(pk=existing.pk).update(
                    count=models.F("count") + 1, title=title, body=body, actor=actor,
                    target=target, updated_at=models.functions.Now(),
                )
                existing.refresh_from_db()
                return existing

        return Notification.objects.create(
            recipient=recipient, kind=kind, title=title, body=body, link=link,
            target=target, actor=actor, dedupe_key=dedupe_key,
        )
    except Exception:  # noqa: BLE001  # 규칙 2
        logger.exception("알림 생성 실패 (kind=%s, recipient=%s)", kind, getattr(recipient, "pk", None))
        return None


def notify_many(recipients, kind, **kwargs) -> list[Notification]:
    """여러 명에게 같은 알림. **수신자는 한 명이므로 N행을 만든다**(모델 docstring 참조)."""
    made = []
    for user in recipients:
        row = notify(user, kind, **kwargs)
        if row is not None:
            made.append(row)
    return made


__all__ = ["notify", "notify_many", "Notification", "NotificationKind"]
