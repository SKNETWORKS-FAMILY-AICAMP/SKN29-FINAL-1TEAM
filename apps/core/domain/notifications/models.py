"""알림 — **메시지 + 이동할 페이지**.

## 알림은 파생이 아니라 저장한다

이 저장소의 규율은 「저장하는 건 사람의 결정뿐, 나머지는 파생」인데(`_context/settlement-ui-rules.md`
§7) 알림은 예외다. 세 가지 이유:

1. **읽음 여부는 사람의 행동**이다 — 저장할 수밖에 없다.
2. **현재 상태에서 역산할 수 없다.** 보완요청을 받았다가 재제출하면 상태는 `SUBMITTED`가
   되어 「보완요청을 받았었다」를 만들 방법이 없다.
3. **비동기 작업 결과는 이벤트 소스가 아예 없다.** 문서 적재 완료·룰 자동 생성은
   `SettlementEvent` 같은 이력이 남지 않는다.

## 수신자는 한 명이다

팀 전체·회계 전체에 보낼 때는 **N행을 만든다**. 다:다로 두면 읽음 상태를 어디에 둘지가
다시 문제가 되고, 「나에게 온 것」을 뽑는 쿼리가 매번 조인이 된다.

## 링크는 서버가 만든다

`link`는 완성된 상대 경로(`/review`)다. 프론트가 「이 종류면 이 경로」를 알면 곧 갈린다 —
플래그 라벨을 프론트가 복사했다가 백엔드 27개 vs 프론트 9개로 어긋났던 자리와 같다.

**지금은 페이지 이동까지만 한다.** 특정 건을 열거나 하이라이트하는 딥링크는 다음 단계다
(받는 쪽 인프라가 저장소에 아직 없다 — `/rules?graph=`를 만드는 코드는 있는데 읽는 코드가
없어서 이미 죽어 있었다).

## 묶기(dedupe)

「팀장이 확인할 건 몇 개」처럼 **개수가 본문인** 알림은 새 행을 쌓지 않고 기존 행의 `count`를
올린다. 팀원이 10건을 올릴 때 알림 10개는 소음이다.

`count`는 **「마지막으로 읽은 뒤 몇 건이 쌓였나」**이지 현재 대기 총량이 아니다. 대기 총량은
파생값이라 알림에 굳히면 화면과 어긋난다 — 총량은 화면에 가서 본다.
"""
from django.conf import settings
from django.db import models


class NotificationKind(models.TextChoices):
    """알림 종류 — **닫힌 목록**이다.

    룰 플래그(`RuleFlag`)는 고객 규정에서 새 어휘가 생기므로 열어 뒀지만, 알림 종류는
    제품이 정하는 것이라 열어 둘 이유가 없다.
    """

    # ── 정산: 나에게 되돌아온 건 ──
    SETTLEMENT_RETURNED = "SETTLEMENT_RETURNED", "보완요청"
    SETTLEMENT_REJECTED = "SETTLEMENT_REJECTED", "반려"
    # ── 정산: 내가 처리해야 할 건 (개수형) ──
    TEAM_COLLECT_PENDING = "TEAM_COLLECT_PENDING", "팀 취합 대기"
    REVIEW_PENDING = "REVIEW_PENDING", "회계 검토 대기"
    # ── 규정 문서 ──
    DOC_INGEST_DONE = "DOC_INGEST_DONE", "규정 문서 처리 완료"
    DOC_INGEST_FAILED = "DOC_INGEST_FAILED", "규정 문서 처리 실패"
    RULE_AUTO_CREATED = "RULE_AUTO_CREATED", "규정에서 룰 자동 생성"
    # ── 룰 콘솔 ──
    RULE_UPDATED = "RULE_UPDATED", "룰 생성·수정 완료"
    RULE_SIMULATION_DONE = "RULE_SIMULATION_DONE", "룰 검증 보고서"
    RULE_ACTIVATION_REQUESTED = "RULE_ACTIVATION_REQUESTED", "룰 활성화 요청"
    RULE_ACTIVATED = "RULE_ACTIVATED", "활성 룰 변경"


#: 종류별 이동 페이지. **서버가 정본**이라 화면이 같은 표를 복사하지 않는다.
LINK_OF = {
    NotificationKind.SETTLEMENT_RETURNED: "/my-expenses",
    NotificationKind.SETTLEMENT_REJECTED: "/my-expenses",
    NotificationKind.TEAM_COLLECT_PENDING: "/team",
    NotificationKind.REVIEW_PENDING: "/review",
    NotificationKind.DOC_INGEST_DONE: "/policy-docs",
    NotificationKind.DOC_INGEST_FAILED: "/policy-docs",
    NotificationKind.RULE_AUTO_CREATED: "/rules",
    NotificationKind.RULE_UPDATED: "/rules",
    NotificationKind.RULE_SIMULATION_DONE: "/rules",
    NotificationKind.RULE_ACTIVATION_REQUESTED: "/rules",
    NotificationKind.RULE_ACTIVATED: "/rules",
}

#: 개수가 본문인 알림 — 새 행을 쌓지 않고 묶는다.
COALESCING_KINDS = {
    NotificationKind.TEAM_COLLECT_PENDING,
    NotificationKind.REVIEW_PENDING,
}


class Notification(models.Model):
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications",
    )
    kind = models.CharField(max_length=32, choices=NotificationKind.choices)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    #: 클릭 시 이동할 상대 경로. 종류에서 파생되지만 **저장한다** — 나중에 경로가 바뀌어도
    #: 과거 알림이 그때의 화면을 가리키게 하는 편이, 없는 화면으로 보내는 것보다 낫다.
    link = models.CharField(max_length=300)
    #: 감사 로그와 같은 표기(`"settlement:123"`). 화면이 열려 있는 대상을 자동 읽음 처리할 때 쓴다.
    target = models.CharField(max_length=100, blank=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    dedupe_key = models.CharField(max_length=160, blank=True, db_index=True)
    count = models.PositiveIntegerField(default=1)
    read_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [
            #: 벨 배지가 매번 도는 쿼리 — 미읽음만 센다.
            models.Index(fields=["recipient", "read_at"], name="ix_notif_recipient_read"),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} → {self.recipient_id}"

    @property
    def unread(self) -> bool:
        return self.read_at is None
