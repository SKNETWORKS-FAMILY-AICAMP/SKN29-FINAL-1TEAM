"""정산 상태머신 서비스 (요구사항 §4.4, FR-ST). 전이는 여기서만 수행."""
from django.db import transaction as db_tx
from django.utils import timezone

from domain.common.models import AuditLog
from domain.erp.models import ErpVoucher
from domain.risk.models import DecisionLabel

from .models import Settlement, SettlementEvent
from .models import SettlementStatus as S

# 허용 전이표 (FR-ST-01). REJECT/ERP_VOUCHER_DRAFTED는 단말.
ALLOWED = {
    S.DRAFT: {S.SUBMITTED},
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


def submit(settlement, actor=None):
    """DRAFT → SUBMITTED (Rule 판정 대기열로)."""
    return transition(settlement, S.SUBMITTED, actor, "제출")


def judge(settlement, actor=None):
    """RPA 1차판정 자리표시자.

    실제 판정은 ai(FastAPI)가 ACTIVE 룰 그래프를 순회해 수행한다(§4.2).
    MVP 백엔드에선 활성 그래프가 없다고 보고 SUBMITTED→RPA_JUDGED→IN_REVIEW로 이관한다.
    """
    transition(settlement, S.RPA_JUDGED, actor, "RPA 1차판정(placeholder)")
    return transition(settlement, S.IN_REVIEW, actor, "Rule 미매칭 → Risk Review 이관")


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
