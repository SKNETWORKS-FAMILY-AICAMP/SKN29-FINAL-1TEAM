"""정산 상태머신 서비스 (요구사항 §4.4, FR-ST). 전이는 여기서만 수행."""
import logging

from django.db import transaction as db_tx
from django.utils import timezone

from domain.common.models import AuditLog
from domain.erp.models import ErpVoucher
from domain.notifications import events as notification_events
from domain.risk import case_index, decision_cases
from domain.risk.models import DecisionLabel

from .models import Settlement, SettlementEvent
from .models import SettlementStatus as S

logger = logging.getLogger(__name__)

# 허용 전이표 (FR-ST-01, 4단계). REJECT/TEAM_REJECTED/ERP_VOUCHER_DRAFTED는 단말.
#  ① 개인(DRAFT) → ② 팀 취합(TEAM_*) → ③ 회계 제출(SUBMITTED)·룰엔진 → ④ 회계 검토·확정
#  개인은 팀 취합으로만 "올림"(DRAFT→TEAM_COLLECTING). 회계 제출(SUBMITTED)은 팀 단계에서만 — 직행 금지(1인 팀도 팀 취합 경유).
ALLOWED = {
    S.DRAFT: {S.TEAM_COLLECTING},
    S.TEAM_COLLECTING: {S.TEAM_RETURNED, S.TEAM_REJECTED, S.SUBMITTED},
    #  **팀 보완요청은 고쳐서 바로 다시 올린다** — 회계 보완요청(`RETURNED → SUBMITTED`)과
    #  같은 모양이다. 예전엔 `{S.DRAFT}`(개인 보유로 되돌리기)만 열려 있었는데 그 전이를
    #  부르는 서비스·API가 없어서, 되받은 건은 「팀에 올림」도 「제출」도 200을 주면서
    #  `skipped`에 담겨 되돌아왔다 — **아무 일도 안 일어나는데 성공처럼 보였다**(실측).
    S.TEAM_RETURNED: {S.TEAM_COLLECTING},   # 보완 후 다시 올림
    S.TEAM_REJECTED: set(),            # 팀 반려(종료)
    S.SUBMITTED: {S.RPA_JUDGED},
    S.RPA_JUDGED: {S.PENDING_CONFIRM, S.RETURNED, S.IN_REVIEW, S.REJECT},
    S.IN_REVIEW: {S.PENDING_CONFIRM, S.RETURNED, S.REJECT},
    #  승인대기에서도 되돌릴 수 있어야 한다 — 룰이 통과시킨 건을 회계 담당자가 열어 보고
    #  "이건 아니다"라고 판단하는 일이 실제로 생긴다. 확정만 허용하면 그 판단을 반영할
    #  방법이 없어, 담당자는 잘못된 줄 알면서 확정하거나 그냥 두게 된다.
    S.PENDING_CONFIRM: {S.CONFIRMED, S.RETURNED, S.REJECT},
    S.CONFIRMED: {S.ERP_VOUCHER_DRAFTED},
    S.RETURNED: {S.SUBMITTED},  # 재제출(FR-ST-04)
    S.REJECT: set(),
    S.ERP_VOUCHER_DRAFTED: set(),
}

# 회계 담당자 검토 결정 → 목표 상태
REVIEW_MAP = {"APPROVE": S.PENDING_CONFIRM, "RETURN": S.RETURNED, "REJECT": S.REJECT}
TEAM_DECISION_MAP = {"RETURN": S.TEAM_RETURNED, "REJECT": S.TEAM_REJECTED}


class TransitionError(Exception):
    pass


@db_tx.atomic
def transition(settlement: Settlement, to_state: str, actor=None, reason: str = "") -> Settlement:
    frm = settlement.status
    if to_state not in ALLOWED.get(frm, set()):
        raise TransitionError(f"{frm} → {to_state} 전이는 허용되지 않습니다.")
    settlement.status = to_state
    settlement.save(update_fields=["status", "updated_at"])
    SettlementEvent.objects.create(
        settlement=settlement, from_state=frm, to_state=to_state, actor=actor, reason=reason
    )
    AuditLog.objects.create(
        actor=actor, action="settlement.transition", target=f"settlement:{settlement.id}",
        before={"status": frm}, after={"status": to_state, "reason": reason},
    )
    #  **알림은 여기서만 만든다.** 전이의 유일한 통로이기 때문이다 — 뷰마다 각자 만들면
    #  하나는 반드시 빠진다(`risk_review`가 judge 액션에만 있어 제출 경로에서 통째로
    #  안 돌던 것과 같은 실수). 알림 실패는 전이를 되돌리지 않는다(`on_transition` 내부에서 흡수).
    notification_events.on_transition(settlement, frm, to_state, actor, reason)
    return settlement


def raise_to_team(settlement, actor=None):
    """DRAFT·TEAM_RETURNED → TEAM_COLLECTING (개인 '올림'·보완 후 재상신).

    1인 팀(영업사원·임원 개인)도 이 단계를 거친다.

    **여기서 룰 판정을 돌린다.** 예전엔 회계 제출 뒤에야 돌아서 팀장이 판정 결과를 못 봤고,
    팀 화면은 "30만원 이상이면 이상건" 같은 프론트 하드코딩으로 이상 여부를 흉내내고 있었다.
    판정을 앞당기면 팀장이 **진짜 근거**로 취합하고, 보완이 필요한 건은 회계까지 갔다
    돌아오지 않고 팀 단계에서 바로 잡힌다.

    **상태는 바꾸지 않는다** — `orchestrator.judge`는 판정만 하고 전이는 하지 않는다.
    `TEAM_COLLECTING → RPA_JUDGED`는 애초에 허용 전이가 아니다(팀장이 올려야 넘어간다).

    판정 실패가 '올림'을 되돌리지 않는다. 올림은 이미 성립했고 판정은 다시 돌릴 수 있다
    (`POST /settlements/{id}/judge/`). 실패를 이유로 롤백하면 개인이 팀에 올릴 수조차 없다.
    """
    from domain.policies import orchestrator

    transition(settlement, S.TEAM_COLLECTING, actor, "팀 취합 올림")
    try:
        orchestrator.judge(settlement)
    except Exception as exc:  # noqa: BLE001  # 조립기·엔진·DB 어느 쪽이든
        logger.warning("정산 %s 팀 취합 판정 실패: %s", settlement.id, exc, exc_info=True)
    return settlement


def submit(settlement, actor=None):
    """TEAM_COLLECTING/RETURNED → SUBMITTED (팀 제출 / 회계 보완요청 재제출). Rule 판정 대기열로."""
    return transition(settlement, S.SUBMITTED, actor, "제출")


# 룰 판정 → 정산 상태 (기술명세서 §4.2(c), FR-RA-02).
#
# **엔진은 최종반려(REJECT)를 만들지 않는다.** 룰 노드가 `decision=REJECT`를 내도 상태는
# `RETURNED`(보완요청)다 — `REJECT`는 재제출이 불가능한 단말이고, 사람이 아닌 규칙이
# 그런 결정을 내리면 되돌릴 방법이 없다. 최종반려는 회계 담당자의 `review()`만 할 수 있다
# ("사람 확정 원칙"). 규칙이 본 위반 사유는 `rule_hits.flags`에 남아 검토 화면에 뜬다.
JUDGE_MAP = {
    "PASS": S.PENDING_CONFIRM,   # 상세검토 생략, 사람 최종확정 대기 (FR-RA-02)
    "RETURN": S.RETURNED,        # 기재·증빙 보완요청
    "REJECT": S.RETURNED,        # 규정 위반 — 보완요청으로 안내(최종반려는 사람만)
    "REVIEW": S.IN_REVIEW,       # Risk Review 이관
}


class RecordedJudgement:
    """팀 취합 때 기록해 둔 판정을 `JudgeResult`처럼 읽게 하는 얇은 어댑터.

    호출부(상태 매핑·감사 사유·API 응답)가 "다시 돌린 판정"과 "기록된 판정"을 구분할
    필요가 없게 한다 — 구분해야 하면 그 분기가 호출부마다 복제된다.
    """

    def __init__(self, summary: dict):
        self._summary = summary or {}

    @property
    def decision(self) -> str:
        return self._summary.get("decision", "REVIEW")

    @property
    def flags(self) -> list:
        return self._summary.get("flags", [])

    @property
    def graph_names(self) -> list:
        return [f"{g.get('name')} v{g.get('version')}" for g in self._summary.get("graphs", [])]

    def to_dict(self) -> dict:
        return dict(self._summary)


def _judge_reason(result) -> str:
    """감사 로그·상태 이력에 남길 한 줄. 왜 그렇게 판정됐는지가 여기서 보여야 한다."""
    where = " → ".join(result.graph_names) or "활성 룰 그래프 없음"
    because = f" · 사유 {', '.join(result.flags)}" if result.flags else ""
    return f"룰 판정 {result.decision} ({where}){because}"[:400]


@db_tx.atomic
def judge(settlement, actor=None, *, reuse_recorded: bool = False):
    """RPA 1차판정을 상태로 옮긴다 (FR-RA-10).

    판정 자체(그래프 선택·엔진 순회·`rule_hits` 기록)는 `policies.orchestrator`가 하고,
    여기서는 그 결정을 상태로 옮기기만 한다. 둘을 갈라 두면 상태를 건드리지 않고
    "지금 규칙으로 다시 돌리면?"을 볼 수 있다.

    ``reuse_recorded=True``면 **엔진을 다시 돌리지 않고** 팀 취합 때 기록해 둔 판정을
    그대로 쓴다. 팀을 거쳐 올라온 건이 그렇다 — 같은 사실에 같은 그래프면 결과가 같은데,
    다시 돌리면 `rule_hits`가 회차별로 쌓여 검토 화면이 어느 게 최신인지 잃는다.
    기록이 없으면(팀 단계에서 판정이 실패했거나 회계 보완요청 재제출이라 팀을 안 거쳤다면)
    여기서 돌린다 — 재제출은 사실이 바뀐 뒤라 옛 판정을 쓰면 안 된다.

    LLM은 개입하지 않는다 — 적용 단계는 결정론적 엔진만 쓴다(FR-RA-06 재현성).
    돌릴 ACTIVE 그래프가 없으면 통과가 아니라 `IN_REVIEW`다(사람에게 넘긴다).

    Returns: 판정 근거(`JudgeResult` 또는 기록된 요약) — 호출부가 그대로 응답에 싣는다.
    """
    from domain.policies import orchestrator

    from . import risk_review

    recorded = settlement.rule_judgement if reuse_recorded else None
    if recorded:
        result = RecordedJudgement(recorded)
    else:
        result = orchestrator.judge(settlement)
    reason = _judge_reason(result)
    transition(settlement, S.RPA_JUDGED, actor, reason)
    transition(settlement, JUDGE_MAP.get(result.decision, S.IN_REVIEW), actor, reason)
    # 검토로 넘어간 건에만 Risk Review Agent를 붙인다. **커밋 후** 실행이라 60초짜리 AI
    # 호출이 이 트랜잭션을 붙들지 않는다. 호출 지점을 여기 하나로 둔 이유는 §risk_review
    # docstring 참조 — 뷰에만 있던 시절 제출 경로에서 통째로 빠졌었다.
    risk_review.schedule(settlement)
    return result


#: 룰이 통과시킨 건을 사람이 되돌릴 때 사유 앞에 붙는 표시.
#  이 문자열이 `SettlementEvent.reason`·`AuditLog`에 그대로 남아, 나중에 "룰은 통과라고
#  했는데 왜 보완요청이 갔지"를 되짚을 수 있다. **판정 이력과 사람의 결정을 구분해 남기지
#  않으면 룰 정밀도 집계가 사람 판단을 룰의 성과로 착각한다.**
RULE_OVERRIDE_MARK = "[룰 통과 → 회계 재분류]"


def _override_note(settlement, decision: str) -> str:
    """룰 판정을 사람이 뒤집는 상황인가 — 맞으면 사유에 붙일 표시를 돌려준다.

    조건은 둘 다 만족할 때다: ① 지금 상태가 **승인대기**(룰이 통과시켜 도착한 자리이거나
    담당자가 이미 승인한 자리) ② 사람의 결정이 보완요청·반려. 검토중(IN_REVIEW)에서
    내리는 결정은 뒤집는 게 아니라 **원래 맡겨진 판단**이라 표시하지 않는다.
    """
    if settlement.status != S.PENDING_CONFIRM or decision not in ("RETURN", "REJECT"):
        return ""
    ruled = settlement.rule_decision or "판정 없음"
    return f"{RULE_OVERRIDE_MARK} 룰 판정={ruled}"


@db_tx.atomic
def review(settlement, decision: str, actor=None, reason: str = ""):
    """회계 담당자 검토 결정. 결과는 decision_labels로 적재(향후 지도학습용)."""
    if decision not in REVIEW_MAP:
        raise TransitionError(f"알 수 없는 결정: {decision}")
    if decision in ("RETURN", "REJECT") and not reason:
        raise TransitionError("보완요청·반려는 사유 입력이 필수입니다.")
    note = _override_note(settlement, decision)
    if note:
        reason = f"{note} {reason}".strip()
    #  사례는 **전이 전에** 판단한다 — 전이 후엔 `rule_decision`·`risk_reviews`는 그대로지만
    #  상태가 바뀌어 "무엇과 다르게 판단했는가"의 맥락(승인대기였는지 검토중이었는지)이 흐려진다.
    case = decision_cases.record(settlement, decision, actor, reason)
    transition(settlement, REVIEW_MAP[decision], actor, reason)
    DecisionLabel.objects.create(settlement=settlement, label=decision, actor=actor)
    if case is not None:
        # 적재는 커밋 후. 실패해도 결정을 되돌리지 않는다(사례는 나중에 다시 올리면 된다).
        case_index.schedule(case)
    return settlement


def team_decide(settlement, decision: str, actor=None, reason: str = ""):
    """팀 취합 단계의 보완요청/반려. 회계 검토 상태와 분리한다(FR-ST-05~06)."""
    if decision not in TEAM_DECISION_MAP:
        raise TransitionError(f"알 수 없는 팀 결정: {decision}")
    return transition(settlement, TEAM_DECISION_MAP[decision], actor, reason)


@db_tx.atomic
def confirm(settlement, actor=None):
    """사람 최종 확정 (FR-ST-03). CONFIRMED 후 ERP 전표(안) 자동 생성 → ERP_VOUCHER_DRAFTED."""
    transition(settlement, S.CONFIRMED, actor, "사람 최종 확정")
    ErpVoucher.objects.get_or_create(
        settlement=settlement,
        defaults={"voucher_payload": _build_voucher(settlement), "status": ErpVoucher.Status.DRAFT},
    )
    return transition(settlement, S.ERP_VOUCHER_DRAFTED, actor, "ERP 전표(안) 생성")


def _build_voucher(settlement) -> dict:
    tx = settlement.transaction
    return {
        "settlement_id": settlement.id,
        "merchant": tx.merchant,
        "amount": int(tx.amount),
        "category": settlement.category or settlement.ai_category,
        "date": tx.ts.date().isoformat(),
        "drafted_at": timezone.now().isoformat(),
    }
