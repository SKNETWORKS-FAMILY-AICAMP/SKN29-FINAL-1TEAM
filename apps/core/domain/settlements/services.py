"""정산 상태머신 서비스 (요구사항 §4.4, FR-ST). 전이는 여기서만 수행."""
from django.db import transaction as db_tx
from django.utils import timezone

from domain.common.models import AuditLog
from domain.erp.models import ErpVoucher
from domain.policies.orchestrator import judge_settlement
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


@db_tx.atomic
def judge(settlement, actor=None):
    """RPA 1차판정 — Rule Agent 오케스트레이션(GLOBAL 필수 게이트 → 계정과목별 scope) 실행(§4.2).

    ACTIVE 그래프가 GLOBAL·scope 둘 다 없으면(판정 근거 없음) IN_REVIEW로 이관한다 —
    이전 placeholder와 그 경우엔 동일하게 동작하지만, 그래프가 있으면 실제로 그 그래프의
    판정(PASS/REJECT/RETURN/REVIEW)을 따른다(`domain.policies.orchestrator.judge_settlement`).
    """
    transition(settlement, S.RPA_JUDGED, actor, "RPA 1차판정")
    target = judge_settlement(settlement)
    reason = "Rule 그래프 판정 완료" if target != S.IN_REVIEW else "Rule 미매칭/REVIEW → Risk Review 이관"
    return transition(settlement, target, actor, reason)


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
