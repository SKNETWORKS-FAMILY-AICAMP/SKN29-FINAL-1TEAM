"""정산 상태머신 서비스 (요구사항 §4.4, FR-ST). 전이는 여기서만 수행."""
from django.db import transaction as db_tx
from django.utils import timezone

from domain.common.models import AuditLog
from domain.erp.models import ErpVoucher
from domain.risk.models import DecisionLabel

from .models import Settlement, SettlementEvent
from .models import SettlementStatus as S

# 허용 전이표 (FR-ST-01, 4단계). REJECT/TEAM_REJECTED/ERP_VOUCHER_DRAFTED는 단말.
#  ① 개인(DRAFT) → ② 팀 취합(TEAM_*) → ③ 회계 제출(SUBMITTED)·룰엔진 → ④ 회계 검토·확정
#  개인은 팀 취합으로만 "올림"(DRAFT→TEAM_COLLECTING). 회계 제출(SUBMITTED)은 팀 단계에서만 — 직행 금지(1인 팀도 팀 취합 경유).
ALLOWED = {
    S.DRAFT: {S.TEAM_COLLECTING},
    S.TEAM_COLLECTING: {S.TEAM_RETURNED, S.TEAM_REJECTED, S.SUBMITTED},
    S.TEAM_RETURNED: {S.DRAFT},        # 개인 수정 후 재상신
    S.TEAM_REJECTED: set(),            # 팀 반려(종료)
    S.SUBMITTED: {S.RPA_JUDGED},
    S.RPA_JUDGED: {S.PENDING_CONFIRM, S.RETURNED, S.IN_REVIEW, S.REJECT},
    S.IN_REVIEW: {S.PENDING_CONFIRM, S.RETURNED, S.REJECT},
    S.PENDING_CONFIRM: {S.CONFIRMED},
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
    return settlement


def raise_to_team(settlement, actor=None):
    """DRAFT → TEAM_COLLECTING (개인 '올림'). 1인 팀(영업사원·임원 개인)도 이 단계를 거친다."""
    return transition(settlement, S.TEAM_COLLECTING, actor, "팀 취합 올림")


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


def _judge_reason(result) -> str:
    """감사 로그·상태 이력에 남길 한 줄. 왜 그렇게 판정됐는지가 여기서 보여야 한다."""
    where = " → ".join(result.graph_names) or "활성 룰 그래프 없음"
    because = f" · 사유 {', '.join(result.flags)}" if result.flags else ""
    return f"룰 판정 {result.decision} ({where}){because}"[:400]


@db_tx.atomic
def judge(settlement, actor=None):
    """RPA 1차판정 — ACTIVE 룰 그래프를 순회해 상태를 정한다 (FR-RA-10).

    판정 자체(그래프 선택·엔진 순회·`rule_hits` 기록)는 `policies.orchestrator`가 하고,
    여기서는 그 결정을 상태로 옮기기만 한다. 둘을 갈라 두면 상태를 건드리지 않고
    "지금 규칙으로 다시 돌리면?"을 볼 수 있다.

    LLM은 개입하지 않는다 — 적용 단계는 결정론적 엔진만 쓴다(FR-RA-06 재현성).
    돌릴 ACTIVE 그래프가 없으면 통과가 아니라 `IN_REVIEW`다(사람에게 넘긴다).

    Returns: `policies.orchestrator.JudgeResult` — 호출부가 판정 근거를 그대로 쓸 수 있다.
    """
    from domain.policies import orchestrator

    result = orchestrator.judge(settlement)
    reason = _judge_reason(result)
    transition(settlement, S.RPA_JUDGED, actor, reason)
    transition(settlement, JUDGE_MAP.get(result.decision, S.IN_REVIEW), actor, reason)
    return result


@db_tx.atomic
def review(settlement, decision: str, actor=None, reason: str = ""):
    """회계 담당자 검토 결정. 결과는 decision_labels로 적재(향후 지도학습용)."""
    if decision not in REVIEW_MAP:
        raise TransitionError(f"알 수 없는 결정: {decision}")
    if decision in ("RETURN", "REJECT") and not reason:
        raise TransitionError("보완요청·반려는 사유 입력이 필수입니다.")
    transition(settlement, REVIEW_MAP[decision], actor, reason)
    DecisionLabel.objects.create(settlement=settlement, label=decision, actor=actor)
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
