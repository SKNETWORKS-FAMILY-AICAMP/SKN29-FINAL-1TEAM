"""사건 → 알림 매핑. **훅이 부르는 유일한 진입점.**

`services.notify()`가 「어떻게 만드나」라면 여기는 「무엇이 알림거리인가」다. 문구도 여기서
만든다 — LLM을 쓰지 않는다(알림은 사실 전달이라 지어낼 여지가 없다).

## 상태 전이 중 알림이 되는 것만

전이가 일어날 때마다 알리면 소음이 된다. `SUBMITTED→RPA_JUDGED`는 기계가 지나간 자리고,
`RPA_JUDGED→RETURNED`가 사람에게 도착한 사건이다. 한 번의 제출로 전이가 2~3회 일어나지만
**사람에게는 하나**다.
"""
from __future__ import annotations

import logging

from domain.accounts.models import Capability
from domain.accounts.queries import users_with_capability

from .models import NotificationKind as K
from .services import notify, notify_many

logger = logging.getLogger(__name__)


def _label(settlement) -> str:
    """알림 제목에 쓸 건 이름 — 가맹점이 없으면 id로."""
    tx = getattr(settlement, "transaction", None)
    merchant = (getattr(tx, "merchant", "") or "").strip()
    return merchant or f"정산 #{settlement.pk}"


def _amount(settlement) -> str:
    tx = getattr(settlement, "transaction", None)
    return f"{int(tx.amount):,}원" if tx is not None else ""


# ════════════════════════════════════════════════════════════════
#  정산 상태 전이
# ════════════════════════════════════════════════════════════════

def on_transition(settlement, from_state: str, to_state: str, actor=None, reason: str = "") -> None:
    """`settlements.services.transition()`이 매 전이마다 부른다.

    **여기서 예외를 올리지 않는다** — 알림 때문에 상태 전이가 롤백되면 안 된다.
    """
    try:
        _dispatch(settlement, to_state, actor, reason)
    except Exception:  # noqa: BLE001
        logger.exception("전이 알림 실패 (settlement=%s, %s→%s)", settlement.pk, from_state, to_state)


def _dispatch(settlement, to_state: str, actor, reason: str) -> None:
    from domain.settlements.models import SettlementStatus as S

    # ── ① 나에게 되돌아온 건 → 지출자 ──
    if to_state in (S.RETURNED, S.TEAM_RETURNED):
        stage = "회계" if to_state == S.RETURNED else "팀장"
        notify(
            settlement.submitted_by, K.SETTLEMENT_RETURNED,
            title=f"보완요청 — {_label(settlement)}",
            #  **사유를 그대로 싣는다.** 요약하면 무엇을 고쳐야 하는지가 사라진다.
            body=f"{stage}이 보완을 요청했습니다. {reason}".strip(),
            target=f"settlement:{settlement.pk}", actor=actor,
        )
        return

    if to_state in (S.REJECT, S.TEAM_REJECTED):
        stage = "회계" if to_state == S.REJECT else "팀장"
        final = "재제출할 수 없습니다." if to_state == S.REJECT else ""
        notify(
            settlement.submitted_by, K.SETTLEMENT_REJECTED,
            title=f"반려 — {_label(settlement)}",
            body=f"{stage}이 반려했습니다. {reason} {final}".strip(),
            target=f"settlement:{settlement.pk}", actor=actor,
        )
        return

    # ── ② 팀장이 확인할 건 (개수형) ──
    if to_state == S.TEAM_COLLECTING:
        team = settlement.team
        if team is None:
            return
        recipients = users_with_capability(Capability.TEAM_AGGREGATE, team=team, exclude=actor)
        notify_many(
            recipients, K.TEAM_COLLECT_PENDING,
            title="팀 취합 대기",
            body=f"{_label(settlement)} {_amount(settlement)} 등이 올라왔습니다.".strip(),
            target=f"team:{team.pk}", actor=actor,
            #  팀 단위로 묶는다 — 팀원이 10건을 올려도 알림은 하나이고 개수만 는다.
            dedupe_key=f"team-collect:{team.pk}",
        )
        return

    # ── ③ 회계가 처리할 건 (개수형) ──
    if to_state in (S.IN_REVIEW, S.PENDING_CONFIRM):
        recipients = users_with_capability(Capability.ACCOUNTING_REVIEW, exclude=actor)
        what = "검토가 필요한 건" if to_state == S.IN_REVIEW else "확정 대기 건"
        notify_many(
            recipients, K.REVIEW_PENDING,
            title=f"{what}이 도착했습니다",
            body=f"{_label(settlement)} {_amount(settlement)}".strip(),
            target=f"settlement:{settlement.pk}", actor=actor,
            #  검토 대기와 확정 대기를 **따로 묶는다** — 성격이 다른 일이라 한 줄로 합치면
            #  "무엇을 해야 하는지"가 사라진다.
            dedupe_key=f"review-pending:{to_state}",
        )
        return


# ════════════════════════════════════════════════════════════════
#  규정 문서 적재 · 룰 자동 생성
# ════════════════════════════════════════════════════════════════

#: `rule_trigger` 결과 중 「룰이 실제로 생겼다」는 상태.
_RULE_CREATED_STATUS = "DRAFT_SAVED"


def on_doc_ingested(doc, *, ok: bool, actor=None) -> None:
    """규정 문서 적재가 끝났다 → **올린 사람에게**.

    적재는 수십 초~분이 걸리고 그동안 사용자는 화면을 떠난다 — 알림이 유일한 통로다.
    """
    try:
        uploader = getattr(doc, "uploaded_by", None)
        if ok:
            notify(
                uploader, K.DOC_INGEST_DONE,
                title=f"규정 문서 처리 완료 — {doc.title}",
                body=f"조항 {doc.chunk_count}건을 색인했습니다. 검색·룰 생성에 쓸 수 있습니다.",
                target=f"policydoc:{doc.pk}", actor=actor,
            )
        else:
            notify(
                uploader, K.DOC_INGEST_FAILED,
                title=f"규정 문서 처리 실패 — {doc.title}",
                body=(doc.error or "사유를 확인할 수 없습니다.")[:300],
                target=f"policydoc:{doc.pk}", actor=actor,
            )
    except Exception:  # noqa: BLE001
        logger.exception("문서 적재 알림 실패 (doc=%s)", getattr(doc, "pk", None))


def on_rule_auto_created(doc, trigger: dict, actor=None) -> None:
    """규정에서 룰이 자동 생성됐다 → **회계팀 전체**.

    올린 사람만 알면 안 된다 — 자동 생성된 룰은 곧 전 정산의 판정 기준이 되므로 회계
    담당자들이 검토·승인 대상이 생겼다는 걸 알아야 한다.

    **생성에 실패했을 때는 이 알림을 만들지 않는다.** 실패 사유는 문서 화면에 남고
    (`PolicyDoc.rule_trigger`), 실패까지 회계 전체에 뿌리면 소음이 된다.
    """
    try:
        if str(trigger.get("status") or "") != _RULE_CREATED_STATUS:
            return
        scope = trigger.get("scope") or trigger.get("requestedScope") or ""
        recipients = users_with_capability(Capability.ACCOUNTING_REVIEW)
        notify_many(
            recipients, K.RULE_AUTO_CREATED,
            title=f"규정에서 룰 초안이 생성됐습니다 — {scope or doc.title}",
            body=f"「{doc.title}」에서 자동 생성된 초안입니다. 검증 후 활성화하세요.",
            target=f"policydoc:{doc.pk}", actor=actor,
        )
    except Exception:  # noqa: BLE001
        logger.exception("룰 자동 생성 알림 실패 (doc=%s)", getattr(doc, "pk", None))


# ════════════════════════════════════════════════════════════════
#  룰 콘솔
# ════════════════════════════════════════════════════════════════

def on_rule_updated(graph, actor=None, *, what: str = "수정") -> None:
    """룰 생성·수정이 끝났다 → **요청한 본인에게**.

    본인에게 보내는데도 `actor`를 넘기지 않는 이유: 이건 「내가 누른 버튼의 결과」가 아니라
    **오래 걸리는 작업이 끝났다**는 알림이다(자기 알림 금지 규칙의 예외).

    화면에 그대로 있으면 결과가 바로 보이므로 알림이 필요 없다 — 그 경우는 룰 콘솔이
    자동으로 읽음 처리한다(`target`으로 대조). 서버는 화면이 어디 있는지 알 수 없으므로
    **항상 만들고 화면이 접는다.**
    """
    try:
        notify(
            actor, K.RULE_UPDATED,
            title=f"룰 {what} 완료 — {graph.name}",
            body=f"v{graph.version} · {graph.scope}",
            target=f"rulegraph:{graph.pk}",
        )
    except Exception:  # noqa: BLE001
        logger.exception("룰 수정 알림 실패 (graph=%s)", getattr(graph, "pk", None))


def on_simulation_done(graph, run, actor=None) -> None:
    """검증 시뮬레이션 보고서가 나왔다 → **실행한 본인에게**."""
    try:
        #  통계는 `RuleSimulationRun.stats`(JSON)에 있다. 키가 없거나 모양이 바뀌어도
        #  알림이 죽지 않게 방어적으로 읽는다 — 여기는 보고서 본문이 아니라 안내다.
        stats = getattr(run, "stats", None) or {}
        graded, failed = stats.get("testGraded"), stats.get("testFailed")
        summary = (
            f"검증 {graded}건 중 기대 불일치 {failed}건"
            if isinstance(graded, int) and isinstance(failed, int)
            else "보고서를 확인하세요."
        )
        notify(
            actor, K.RULE_SIMULATION_DONE,
            title=f"룰 검증 보고서 — {graph.name}",
            body=f"v{graph.version} · {summary}",
            target=f"rulegraph:{graph.pk}",
        )
    except Exception:  # noqa: BLE001
        logger.exception("시뮬레이션 알림 실패 (graph=%s)", getattr(graph, "pk", None))


def on_activation_requested(graph, comment: str, actor=None) -> None:
    """활성화 승인 요청 → **승인 권한이 있는 사람에게**(`rule_activate`)."""
    try:
        recipients = users_with_capability(Capability.RULE_ACTIVATE, exclude=actor)
        notify_many(
            recipients, K.RULE_ACTIVATION_REQUESTED,
            title=f"룰 활성화 승인 요청 — {graph.name}",
            body=f"v{graph.version} · {graph.scope}\n{comment}".strip(),
            target=f"rulegraph:{graph.pk}", actor=actor,
        )
    except Exception:  # noqa: BLE001
        logger.exception("활성화 요청 알림 실패 (graph=%s)", getattr(graph, "pk", None))


def on_rule_activated(graph, actor=None) -> None:
    """활성 룰이 바뀌었다 → **회계팀 전체**.

    이 순간부터 모든 정산이 새 그래프로 판정된다. 승인자만 아는 변경이면, 판정 결과가
    달라진 이유를 나머지 담당자가 설명할 수 없다.
    """
    try:
        recipients = users_with_capability(Capability.ACCOUNTING_REVIEW)
        notify_many(
            recipients, K.RULE_ACTIVATED,
            title=f"활성 룰이 변경됐습니다 — {graph.scope}",
            body=f"{graph.name} v{graph.version}가 활성화됐습니다. 이후 정산은 이 규칙으로 판정됩니다.",
            target=f"rulegraph:{graph.pk}", actor=actor,
        )
    except Exception:  # noqa: BLE001
        logger.exception("활성 룰 변경 알림 실패 (graph=%s)", getattr(graph, "pk", None))
