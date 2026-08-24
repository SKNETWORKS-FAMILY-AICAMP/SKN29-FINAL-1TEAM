"""판정 스냅샷 → **사람이 눈으로 못 보는 것**만 골라 문장으로 편다.

## 왜 필요한가

보고서의 `highlights`("이 거래에서 눈여겨볼 점")가 그동안 결제 시각·금액·업종 같은
**화면에 이미 보이는 것**을 되풀이했다. 검토자는 그걸 목록에서 이미 봤다 — 보고서가
할 일은 **화면에 안 보이는 것**을 짚는 것이다.

안 보이는 것은 두 곳에 있다:
  · **EvalContext 스냅샷** — 이력 집계(같은 가맹점 반복·일/월 누적), 신고 인원과 문서로
    확인된 인원의 차이, 업종 판정 신뢰도, 실사용자와 지출자의 불일치. 화면 어디에도 없다.
  · **사유 플래그** — 특히 `UNRESOLVED_FACT:<경로>`. "무엇을 몰라서 검토로 왔는가"인데
    코드로만 남아 있어 담당자가 읽지 못한다.

## 왜 LLM에게 원본을 통째로 주지 않는가

54개 경로를 그대로 던지면 모델이 **아무거나** 고른다(그리고 대개 눈에 띄는 금액·시각을
고른다 — 화면에 이미 있는 것들이다). 여기서 **무엇이 눈여겨볼 만한지의 판단은 코드가**
하고, 모델은 그걸 사람 말로 옮긴다. 판정을 모델이 예측하지 않게 하는 것(`narrate.py`)과
같은 분업이다.

**임계값이 코드에 박혀 있다**(반복 3회·소진율 80% 등). 이건 판정이 아니라 **보고서에
무엇을 적을지**의 기준이라 룰 엔진과 다른 축이다 — 틀려도 판정은 안 바뀌고 문장만 는다.
"""
from __future__ import annotations

from typing import Any

#: 같은 가맹점을 이만큼 이상 반복하면 적는다. 판정 기준이 아니라 **서술 기준**이다.
SAME_VENDOR_MIN = 3
#: 한도 대비 소진율이 이 이상이면 "한도에 근접"이라고 적는다.
LIMIT_NEAR_RATIO = 0.8
#: 업종 판정 신뢰도가 이 미만이면 "업종이 불확실"이라고 적는다.
LOW_INDUSTRY_CONFIDENCE = 0.7


def _get(ctx: dict, section: str, name: str) -> Any:
    return (ctx.get(section) or {}).get(name)


def _won(value: Any) -> str:
    try:
        return f"{int(value):,}원"
    except (TypeError, ValueError):
        return str(value)


def notables(ctx: dict[str, Any], flags: list[dict] | None = None) -> list[str]:
    """눈여겨볼 사실 문장 목록. **없으면 빈 목록**(채우려고 지어내지 않는다)."""
    if not ctx:
        return []
    out: list[str] = []

    # ── 이력 — 화면에 아예 없다. 한 건만 보는 검토자가 가장 못 보는 것.
    same_vendor = _get(ctx, "history", "same_vendor_count")
    if isinstance(same_vendor, int) and same_vendor >= SAME_VENDOR_MIN:
        out.append(f"같은 가맹점을 집계 기간에 {same_vendor}회 결제했습니다(이 건 포함).")

    for path, label in (("daily_cumulative_amount", "같은 날"),
                        ("monthly_cumulative_amount", "같은 달")):
        used = _get(ctx, "history", path)
        limit = _get(ctx, "policy", "position_daily_limit" if "daily" in path
                     else "position_monthly_limit")
        if isinstance(used, (int, float)) and isinstance(limit, (int, float)) and limit:
            ratio = used / limit
            if ratio >= LIMIT_NEAR_RATIO:
                tail = ("직책 한도를 초과했습니다" if ratio >= 1
                        else f"직책 한도의 {ratio * 100:.0f}%를 썼습니다")
                out.append(
                    f"{label} 본인 누적 결제액이 {_won(used)}입니다 — "
                    f"{tail}(한도 {_won(limit)})."
                )

    # ── 신고 인원 vs 문서 확인 인원 — 둘 다 화면에 안 나온다.
    reported = _get(ctx, "participants", "participant_count")
    verified = _get(ctx, "participants", "verified_participant_count")
    if isinstance(reported, int) and isinstance(verified, int) and reported != verified:
        out.append(
            f"본인이 적은 참석 인원({reported}명)과 첨부 문서에서 확인된 인원({verified}명)이 "
            "다릅니다."
        )
    elif isinstance(reported, int) and verified is None:
        out.append(
            f"참석 인원 {reported}명은 **본인 신고값**입니다 — 명단·회의록으로 확인되지 "
            "않았습니다."
        )

    # ── 실사용자 — 공용·팀 카드에서만 뜻이 있다.
    if _get(ctx, "card", "actual_user_is_spender") is False:
        out.append("카드를 실제로 쓴 사람과 정산을 올린 사람이 다릅니다.")

    # ── 업종 판정 신뢰도 — 화면은 업종 이름만 보여준다.
    confidence = _get(ctx, "merchant", "industry_confidence")
    if isinstance(confidence, (int, float)) and confidence < LOW_INDUSTRY_CONFIDENCE:
        merchant_type = _get(ctx, "merchant", "merchant_type") or "미상"
        out.append(
            f"가맹점 업종을 「{merchant_type}」으로 봤지만 판정 신뢰도가 낮습니다"
            f"({confidence:.0%}) — 업종에 걸리는 규정이 있다면 직접 확인이 필요합니다."
        )

    # ── 제출 지연 — 기한은 별표에서 오고, 화면은 둘 다 안 보여준다.
    elapsed = _get(ctx, "derived", "business_days_since_expense")
    deadline = _get(ctx, "policy", "settlement_deadline_days")
    if isinstance(elapsed, int) and isinstance(deadline, (int, float)) and elapsed > deadline:
        out.append(f"결제일로부터 {elapsed}영업일이 지났습니다(제출 기한 {int(deadline)}영업일).")

    # ── 판단하지 못한 사실 — 코드로만 남아 있어 담당자가 읽지 못한다.
    unresolved = [
        f.get("arg") for f in (flags or [])
        if str(f.get("code") or "").startswith("UNRESOLVED") and f.get("arg")
    ]
    if unresolved:
        out.append(
            "다음 정보를 확인할 수 없어 자동 판정이 보류됐습니다: "
            + ", ".join(_readable_path(p) for p in unresolved) + "."
        )
    return out


#: 내부 경로를 담당자 말로. 목록에 없으면 **경로를 노출하지 않고** 뭉뚱그린다 —
#  `evidence.has_valid_receipt` 같은 문자열이 보고서에 나오면 그건 우리 사정이지
#  담당자가 읽을 문장이 아니다.
_PATH_KO = {
    "approval.pre_approval_obtained": "사전승인 여부",
    "participants.participant_count": "참석 인원(신고)",
    "participants.verified_participant_count": "참석 인원(문서 확인)",
    "participants.external_participant_count": "외부 참석 인원",
    "participants.has_kickback_law_target": "청탁금지법 대상자 참석 여부",
    "category.item_type": "지출 세부유형",
    "category.value": "비용분류",
    "merchant.merchant_type": "가맹점 업종",
    "merchant.forbidden": "금지업종 해당 여부",
    "evidence.has_valid_receipt": "적격증빙 첨부 여부",
    "tx.per_person_amount": "1인당 금액(신고 인원 기준)",
    "tx.verified_per_person_amount": "1인당 금액(확인 인원 기준)",
    "trip.trip_type": "출장 구분",
    "trip.region_grade": "출장 지역등급",
    "trip.lodging_amount_per_night": "1박 숙박비",
    "dining.includes_alcohol": "주류 포함 여부",
    "dining.is_secondary_venue": "2차 여부",
    "card.actual_user_recorded": "실사용자 등록 여부",
}


def _readable_path(path: str) -> str:
    if path in _PATH_KO:
        return _PATH_KO[path]
    section = str(path).split(".", 1)[0]
    return {
        "policy": "규정 한도값", "history": "과거 결제 이력", "user": "지출자 정보",
        "derived": "계산된 값", "participants": "참석자 정보", "trip": "출장 정보",
    }.get(section, "일부 판정 정보")
