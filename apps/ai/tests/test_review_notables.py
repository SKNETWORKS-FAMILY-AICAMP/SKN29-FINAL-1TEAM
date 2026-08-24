"""`review_notables` 회귀 — 보고서가 **화면에 없는 것만** 짚는지.

여기서 지키는 계약 셋:

① **화면에 이미 있는 것은 안 적는다.** 금액·가맹점·결제 시각은 검토 목록에 떠 있다 —
   보고서가 되풀이하면 담당자는 다음부터 그 칸을 안 읽는다.

② **없으면 비운다.** 채우려고 지어내지 않는다. 빈 목록이면 프롬프트가 "(없음)"을 받고
   모델도 highlights를 비운다.

③ **내부 경로를 노출하지 않는다.** `evidence.has_valid_receipt` 같은 문자열이 보고서에
   나오면 그건 우리 사정이지 담당자가 읽을 문장이 아니다.
"""
from __future__ import annotations

from app.agents.review_notables import notables


def ctx(**sections):
    base = {
        "tx": {}, "card": {}, "user": {}, "merchant": {}, "category": {},
        "evidence": {}, "approval": {}, "participants": {}, "trip": {},
        "dining": {}, "history": {}, "policy": {}, "derived": {},
    }
    for key, value in sections.items():
        base[key] = value
    return base


# ── ② 없으면 비운다 ──────────────────────────────────────────────────────

def test_스냅샷이_없으면_빈_목록이다():
    assert notables({}, []) == []


def test_평범한_건은_짚을_것이_없다():
    assert notables(ctx(history={"same_vendor_count": 1})) == []


def test_화면에_있는_사실만으로는_짚지_않는다():
    """금액·시각·업종은 검토 목록에 이미 있다."""
    assert notables(ctx(
        tx={"amount": 450_000, "payment_time": "23:40"},
        merchant={"merchant_type": "일반음식점", "industry_confidence": 0.95},
    )) == []


# ── ① 화면에 없는 것 ─────────────────────────────────────────────────────

def test_같은_가맹점_반복은_짚는다():
    out = notables(ctx(history={"same_vendor_count": 4}))
    assert len(out) == 1 and "4회" in out[0]


def test_반복이_적으면_짚지_않는다():
    assert notables(ctx(history={"same_vendor_count": 2})) == []


def test_한도에_근접하면_짚는다():
    out = notables(ctx(
        history={"daily_cumulative_amount": 450_000},
        policy={"position_daily_limit": 500_000},
    ))
    assert len(out) == 1
    assert "450,000원" in out[0] and "500,000원" in out[0] and "90%" in out[0]


def test_한도를_넘으면_초과라고_적는다():
    out = notables(ctx(
        history={"monthly_cumulative_amount": 3_000_000},
        policy={"position_monthly_limit": 2_000_000},
    ))
    assert "초과" in out[0] and "같은 달" in out[0]


def test_한도가_없으면_비교하지_않는다():
    """한도를 모르는데 「근접」이라고 쓸 수 없다."""
    assert notables(ctx(history={"daily_cumulative_amount": 9_000_000})) == []


def test_신고_인원과_확인_인원이_다르면_짚는다():
    out = notables(ctx(participants={
        "participant_count": 6, "verified_participant_count": 4,
    }))
    assert len(out) == 1 and "6명" in out[0] and "4명" in out[0]


def test_신고만_있으면_확인되지_않았다고_적는다():
    out = notables(ctx(participants={"participant_count": 6}))
    assert len(out) == 1 and "신고" in out[0]


def test_인원이_같으면_짚지_않는다():
    assert notables(ctx(participants={
        "participant_count": 4, "verified_participant_count": 4,
    })) == []


def test_실사용자가_다르면_짚는다():
    out = notables(ctx(card={"actual_user_is_spender": False}))
    assert len(out) == 1 and "다릅니다" in out[0]


def test_실사용자가_같거나_모르면_짚지_않는다():
    assert notables(ctx(card={"actual_user_is_spender": True})) == []
    assert notables(ctx(card={"actual_user_is_spender": None})) == []


def test_업종_신뢰도가_낮으면_짚는다():
    out = notables(ctx(merchant={"merchant_type": "카페", "industry_confidence": 0.4}))
    assert len(out) == 1 and "카페" in out[0] and "40%" in out[0]


def test_제출_기한을_넘기면_짚는다():
    out = notables(ctx(
        derived={"business_days_since_expense": 12},
        policy={"settlement_deadline_days": 7},
    ))
    assert len(out) == 1 and "12영업일" in out[0] and "7영업일" in out[0]


# ── ③ 미해소 사실 ────────────────────────────────────────────────────────

def test_판단하지_못한_사실을_사람_말로_옮긴다():
    out = notables(ctx(), [
        {"code": "UNRESOLVED_FACT", "arg": "approval.pre_approval_obtained"},
        {"code": "UNRESOLVED_POLICY_VAR", "arg": "kickback_limit"},
    ])
    assert len(out) == 1
    assert "사전승인 여부" in out[0]
    #  내부 경로가 그대로 나오면 안 된다.
    assert "approval.pre_approval_obtained" not in out[0]


def test_모르는_경로는_경로를_노출하지_않고_뭉뚱그린다():
    out = notables(ctx(), [{"code": "UNRESOLVED_FACT", "arg": "history.some_new_field"}])
    assert "과거 결제 이력" in out[0]
    assert "history.some_new_field" not in out[0]


def test_미해소가_아닌_플래그는_이_칸에_안_들어간다():
    """사유 플래그는 판정 패널이 이미 보여준다 — 여기 다시 적으면 두 곳이 같은 말을 한다."""
    assert notables(ctx(), [{"code": "EVIDENCE_MISSING", "arg": ""}]) == []


def test_여러_가지가_겹치면_모두_짚는다():
    out = notables(
        ctx(
            history={"same_vendor_count": 5},
            participants={"participant_count": 8, "verified_participant_count": 3},
            card={"actual_user_is_spender": False},
        ),
        [{"code": "UNRESOLVED_FACT", "arg": "category.item_type"}],
    )
    assert len(out) == 4
