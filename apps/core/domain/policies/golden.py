"""룰엔진 검증셋 — **확실하게 판단 가능한 건**만 모은 골든 케이스.

## 왜 코드로 만드나

`seed_adopted`가 남기는 골든(185건)은 「적용이 끝난 회사의 정상 분포」라 보완반려가
7건뿐이다. 그걸로는 **오탐을 잴 수 없다** — 틀리게 확정할 기회 자체가 거의 없다.

여기서는 정답이 자명한 케이스만 골라 300건을 만든다. 각 케이스는 EvalContext를 직접
조립하므로 **DB도 시드도 필요 없고**, 룰 버전을 바꿔 가며 즉시 채점할 수 있다
(`run_rule_engine(ctx, snapshot)`은 순수 함수다).

## 라벨의 뜻

  · **승인** — 규정상 문제가 없어 승인해도 되는 건. 룰이 `PASS`로 확정해야 맞다.
  · **보완반려** — 규정 위반이 명백해 되돌려야 하는 건. `RETURN`/`REJECT`로 확정해야 맞다.

**애매한 건은 넣지 않는다.** 검토(`REVIEW`)가 정답인 케이스를 섞으면 「확정을 맞게 했는가」를
못 재고, 검토를 실패로 오해하게 만든다([[rule-engine-semantics]] §4).

## 사실은 전부 명시한다

`None`은 「모른다」이고 미해소 가드가 판정을 검토로 낮춘다. 검증셋은 **판단 가능한 건**만
담으므로, 룰이 참조할 사실은 빠짐없이 채운다 — 안 채우면 룰이 틀려서가 아니라 사실이
없어서 검토로 가고, 그건 이 검증셋이 재려는 것이 아니다.
"""
from __future__ import annotations

import random
from typing import Any

from .eval_context import empty_eval_context

#: 별표에서 오는 임계값. 판정에 실제로 쓰이는 값과 같아야 한다
#  (`tiger_tables.py` · 실제 규정 별표에서 추출한 값).
POLICY = {
    "preapproval_threshold": 500_000,
    "position_daily_limit": 300_000,
    "position_monthly_limit": 3_000_000,
    "kickback_limit": 50_000,
    "lodging_limit": 150_000,
    "evidence_threshold": 30_000,
    "dining_per_person_limit": 50_000,
    "settlement_deadline_days": 30,
}

APPROVE, BLOCK = "승인", "보완반려"


def _ctx(**over: Any) -> dict[str, Any]:
    """정상 건의 EvalContext를 만들고 `over`로 덮는다.

    기본값은 **모든 검사를 통과하는 상태**다 — 위반 케이스는 필요한 한 가지만 뒤집는다.
    그래야 「무엇 때문에 걸렸는가」가 케이스 하나당 하나로 남는다.
    """
    ctx = empty_eval_context()
    ctx["tx"].update(amount=45_000, payment_method="법인카드", payment_time="12:30",
                     per_person_amount=15_000, verified_per_person_amount=15_000)
    ctx["card"].update(card_type="PERSONAL", actual_user_is_spender=True,
                       actual_user_recorded=True)
    ctx["user"].update(job_title="비직책자", job_title_rank=1, team="영업팀", bu="영업본부")
    ctx["merchant"].update(merchant_type="일반음식점", merchant_info_resolved=True,
                           industry_confidence=0.95, forbidden=False)
    ctx["category"].update(value="식대", item_type="식사", confidence=0.9)
    ctx["evidence"].update(has_valid_receipt=True, expense_purpose_missing=False,
                           has_meeting_minutes=True, has_participant_list=True,
                           has_trip_plan=True, has_contract=True)
    ctx["approval"].update(pre_approval_obtained=True)
    ctx["participants"].update(participant_count=3, verified_participant_count=3,
                               external_participant_count=0, verified_external_count=0,
                               has_kickback_law_target=False)
    ctx["trip"].update(trip_type="국내당일", region_grade="A", lodging_amount_per_night=None)
    ctx["dining"].update(includes_alcohol=False, is_secondary_venue=False,
                         gathering_unit="팀", gathering_type="팀")
    ctx["history"].update(daily_cumulative_amount=45_000, monthly_cumulative_amount=800_000,
                          same_vendor_count=1)
    ctx["derived"].update(is_weekend=False, business_days_since_expense=3)
    ctx["policy"].update(POLICY)

    for section, values in over.items():
        ctx[section].update(values)
    return ctx


def _case(label: str, scope: str, name: str, **over: Any) -> dict[str, Any]:
    """`scope`는 비용분류이자 **과목 그래프를 고르는 키**다.

    이름이 `category`가 아닌 이유: `over`에도 `category=` 섹션이 올 수 있어 충돌한다.
    """
    ctx = _ctx(**over)
    ctx["category"]["value"] = scope
    return {"label": label, "category": scope, "name": name, "ctx": ctx}


def build(seed: int = 20260825) -> list[dict[str, Any]]:
    """골든 300건. **결정적**이다(같은 seed면 같은 목록)."""
    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []

    # ══════════════════════════════════════════ 승인 — 180건
    #  과목마다 30건. 금액·가맹점·시각만 흔들고 **판정에 걸릴 사실은 전부 정상**이다.
    normal = {
        "식대": dict(merchant_type="일반음식점", item_type="식사", lo=8_000, hi=90_000),
        "회의": dict(merchant_type="카페", item_type="식사", lo=6_000, hi=120_000),
        "접대": dict(merchant_type="일반음식점", item_type="식사", lo=50_000, hi=280_000),
        "회식": dict(merchant_type="일반음식점", item_type="식사", lo=120_000, hi=290_000),
        "출장": dict(merchant_type="주유/교통", item_type="교통", lo=20_000, hi=250_000),
        "기타": dict(merchant_type="문구/사무용품", item_type="소모품", lo=10_000, hi=180_000),
    }
    for scope, spec in normal.items():
        for i in range(30):
            amount = rng.randrange(spec["lo"], spec["hi"], 500)
            #  인원은 1인당 한도를 넘지 않게 잡는다 — 정상 건이므로.
            people = max(2, amount // 40_000 + 1)
            rows.append(_case(
                APPROVE, scope, f"{scope} 정상 {i + 1}",
                tx=dict(amount=amount, per_person_amount=amount // people,
                        verified_per_person_amount=amount // people,
                        payment_time=f"{rng.randint(11, 19):02d}:{rng.choice(['00', '15', '30'])}"),
                merchant=dict(merchant_type=spec["merchant_type"]),
                category=dict(item_type=spec["item_type"]),
                participants=dict(participant_count=people, verified_participant_count=people),
                history=dict(daily_cumulative_amount=amount,
                             monthly_cumulative_amount=rng.randrange(300_000, 2_500_000, 10_000)),
            ))

    # ══════════════════════════════════════════ 보완반려 — 120건
    #  **위반 하나만 뒤집는다.** 두 개를 겹치면 어느 룰이 잡았는지 알 수 없고,
    #  한 룰을 빼도 다른 룰이 가려 주어 결함이 안 드러난다.
    def blocked(scope: str, name: str, n: int, **over: Any) -> None:
        for i in range(n):
            rows.append(_case(BLOCK, scope, f"{name} {i + 1}", **over))

    # ── 공통 게이트가 잡아야 할 것 (40건) ──────────────────────────
    blocked("식대", "금지업종(주점/유흥)", 8,
            merchant=dict(merchant_type="주점/유흥", forbidden=True),
            tx=dict(amount=180_000, payment_time="23:30"))
    blocked("기타", "금지업종(사행성)", 6,
            merchant=dict(merchant_type="사행성업종", forbidden=True),
            tx=dict(amount=250_000))
    blocked("기타", "현금성(상품권)", 8,
            category=dict(item_type="상품권"), tx=dict(amount=300_000))
    blocked("회식", "공용카드 실사용자 미기재", 10,
            card=dict(card_type="TEAM", actual_user_recorded=False, actual_user_is_spender=False),
            tx=dict(amount=280_000))
    blocked("식대", "적격증빙 없음", 8,
            evidence=dict(has_valid_receipt=False), tx=dict(amount=120_000))

    # ── 접대(업무추진비) 규정 (30건) ───────────────────────────────
    #  근거: 업무추진비 사용규정 제11조②(3만 초과 적격증빙)·제12조①(사전승인)·
    #        별표1(청탁금지법 대상자 1인당 한도)·제11조④(참석자 명단)
    blocked("접대", "3만원 초과 적격증빙 없음", 8,
            evidence=dict(has_valid_receipt=False), tx=dict(amount=150_000),
            category=dict(item_type="식사"))
    blocked("접대", "50만원 초과 사전승인 없음", 8,
            approval=dict(pre_approval_obtained=False), tx=dict(amount=800_000),
            participants=dict(participant_count=6, verified_participant_count=6))
    #  ⚠️ **청탁금지법 건은 검증셋에 넣지 않는다.** 한도 초과 자체는 규칙으로 확정할 수
    #  있지만, 법 위반 소지가 있는 건은 **자동 반려도 자동 승인도 위험**해 `E-03`이 일부러
    #  `REVIEW`를 낸다. 「확정을 맞게 했는가」를 재는 검증셋에 넣으면 그 정책적 선택이
    #  오탐으로 잡히거나 자동처리율을 깎는다 — 재려는 것이 아니다.
    blocked("접대", "사전승인 없이 고액 집행", 8,
            approval=dict(pre_approval_obtained=False), tx=dict(amount=1_200_000),
            participants=dict(participant_count=8, verified_participant_count=8))
    blocked("접대", "참석자 명단 없음", 6,
            participants=dict(participant_count=0, verified_participant_count=0),
            evidence=dict(has_participant_list=False), tx=dict(amount=190_000))

    # ── 회식 규정 (30건) ──────────────────────────────────────────
    #  근거: 회식 운영규정 제7조(1인당 식대 권장 한도·총액 30만 사전승인)·
    #        제5조(2차 비용 불가)
    blocked("회식", "1인당 한도 초과", 10,
            tx=dict(amount=420_000, per_person_amount=105_000,
                    verified_per_person_amount=105_000),
            participants=dict(participant_count=4, verified_participant_count=4),
            dining=dict(gathering_unit="팀"))
    blocked("회식", "2차 비용", 10,
            dining=dict(is_secondary_venue=True, includes_alcohol=True),
            tx=dict(amount=180_000, payment_time="23:10"),
            merchant=dict(merchant_type="주점/유흥", forbidden=True))
    blocked("회식", "총액 30만 초과 사전승인 없음", 10,
            approval=dict(pre_approval_obtained=False), tx=dict(amount=450_000),
            participants=dict(participant_count=9, verified_participant_count=9),
            dining=dict(gathering_unit="부서"))

    # ── 출장 규정 (20건) ──────────────────────────────────────────
    #  근거: 출장비 사용규정 제17조②(지역등급별 1박 숙박비 상한)
    blocked("출장", "국내 숙박비 상한 초과", 10,
            trip=dict(trip_type="국내숙박", region_grade="A",
                      lodging_amount_per_night=280_000),
            tx=dict(amount=560_000))
    blocked("출장", "해외 숙박비 상한 초과", 10,
            trip=dict(trip_type="해외", region_grade="C",
                      lodging_amount_per_night=320_000),
            tx=dict(amount=960_000))

    return rows
