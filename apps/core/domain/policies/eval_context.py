"""EvalContext 스키마 계약과 조립 경계 (FR-RA-08).

실제 facts 조립은 이 모듈만 ORM/외부 조회를 사용한다. DSL과 엔진은 이 모듈이
반환한 JSON 직렬화 가능한 dict만 읽는다.
"""

from __future__ import annotations

from typing import Any, NamedTuple, TypedDict


EVAL_CONTEXT_SCHEMA_VERSION = 6
BUILDER_VERSION = "6.0"

# ─────────────────────────────────────────────────────────────────────────────
# 정적 카탈로그. ACTIVE 전환 게이트(`validate_graph_vars`)와 룰 편집 UI가 사용한다.
#
# **원칙: EvalContext는 '단어'만 제공한다. '문장'(판단)은 룰 그래프가 조합한다.**
#
# 필드가 여기 있으려면 셋 다 만족해야 한다:
#   ① 관찰(observation)이지 판정(verdict)이 아니다
#   ② 다른 필드로부터 DSL 연산자(and/or/not/비교/in)로 조합할 수 없다
#   ③ 현실적인 출처가 있다 (SoR · 첨부문서 추출 · 별표 룩업)
#
# v3 다이어트 (101 → 47) — `_context/eval-context-sourcing.md` §12
#   (a) **판정 필드 제거**: `derived.personal_use_suspected`·`category_specific_*`·
#       `evidence.purpose_is_generic` 등은 그 자체가 결론이다. 원자 사실을 그래프에서
#       조합해 판단하게 한다.
#   (b) **조합 가능 필드 제거**: `*_missing` 계열은 대상 필드의 유무로 판정 가능하다.
#       (`None`=모름 계약이 있으므로 "누락"을 별도 불린으로 둘 이유가 없다)
#   (c) **원천 없고 부차적인 필드 제거**: `tx.service_charge_ratio`(영수증 미표기 빈번)·
#       `tx.is_holiday`(공휴일 캘린더 부재)·`merchant.merchant_grade` 등
#   (d) **과세분화 제거**: 출장 상세 9종·참석자 상세 5종·세부유형 3종
#   되살릴 때는 원천(모델/추출)을 먼저 확보하고 그 다음 필드를 추가한다. 순서를 지킨다.
#
# v6 결정 (2026-08-23) — **파생 불린을 두지 않는다. 상수는 룰에 허용한다.**
#   조립기가 `is_late_night`(22~06)·`is_working_hours`(09~18)처럼 **판단 기준을 코드에 박고**
#   불린으로 접어 주면, 그 숫자를 바꾸려고 Django를 재배포해야 한다. 회사마다 다른 값이고
#   룰은 Rule Agent가 관리한다 — 그래프가 `tx.payment_time >= "22:00"`으로 직접 쓰는 편이
#   유연하다. **룰 조건에 상수가 박히는 것은 허용한다**(팀 결정): 내규 개정은 잦지 않고,
#   개정 시 고칠 대상이 조립기 코드가 아니라 룰 그래프인 편이 낫다.
#
#   삭제(4): `derived.is_late_night` · `user.is_working_hours` ← `tx.payment_time` 비교로 대체
#            `evidence.has_supporting_evidence` ← 첨부 종류별 불린의 `or`
#            `user.finance_dept_is_spender` ← `user.team == "재무회계팀"`
#
#   **예외 셋은 남긴다** — 이건 취향이 아니라 DSL의 구조적 한계다:
#     ① **null 여부**(`merchant.merchant_info_resolved`) — 미해소 가드가 참조 경로의 `None`을
#        보고 값 평가 **전에** REVIEW로 강등하므로, `x == null`을 룰로 표현할 수 없다.
#     ② **별표 선해소**(`merchant.forbidden`) — DSL에 룩업 연산자가 없다. 리터럴 목록으로
#        풀면 규정 개정을 못 따라간다.
#     ③ **산술·날짜**(`derived.is_weekend`·`business_days_since_expense`·`tx.per_person_amount`)
#        — DSL에 연산자·요일 함수가 없다. 원자(요일)가 스키마에 없어 조합도 불가능하다.
#   남기는 불린은 **왜 예외인지를 설명에 적는다**. 이유가 없는 파생 불린은 지워도 되는 것이다.
#
# v2 유산 (유지되는 규율)
#   · **필드명에 상수를 넣지 않는다.** `biz_days_over_7`·`*_3m`처럼 숫자가 이름에 박히면
#     규정 개정이 스키마 변경이 된다. "무엇을 재는가"만 이름에, "얼마인가"는 policy.*에.
#   · `policy.*`는 별표(`PolicyTable`) 선해소 스칼라다 — DSL은 스칼라 비교만 한다.
#   ※ 기존 스냅샷은 v1/v2다. 소급 수정하지 않고 `rule_hits.eval_context_schema_version`으로 구분한다.
# ─────────────────────────────────────────────────────────────────────────────
class FieldSpec(NamedTuple):
    """필드 하나의 계약. **설명은 그대로 LLM 프롬프트에 나간다**(`domain/context`).

    경로 문자열만 주면 모델이 극성·단위를 추측한다(`evidence.expense_purpose_missing`
    처럼 뒤집힌 필드가 실재한다). 설명을 문서가 아니라 여기 두는 이유다 — 문서는
    갱신을 잊어도 조용하지만, 여기 있으면 프롬프트가 곧바로 틀려서 눈에 띈다.

    `enum`은 값 어휘가 따로 있는 필드가 그 어휘 섹션을 가리킨다. `in [...]`의 우변을
    모델이 지어내지 못하게 하는 장치다(어긋난 표기는 에러가 아니라 **조용한 미발동**이 된다).
    """
    type: str            # number | integer | boolean | string | time
    desc: str
    enum: str = ""       # vocab.card_type | vocab.org | vocab.industry | vocab.category | vocab.item_type


_F = FieldSpec

_SCHEMA_FIELDS: dict[str, dict[str, FieldSpec]] = {
    # 거래 사실 — day_of_week/is_holiday는 derived.is_weekend로 갈음, service_charge_ratio 제외
    "tx": {
        "amount": _F("number", "건당 결제 총액(원)."),
        "per_person_amount": _F(
            "number",
            "1인당 환산액(원) = 총액 ÷ **신고** 인원. 인원을 모르면 null. 신고값 기반이라 "
            "승인이 느슨한 지출에 쓴다.",
        ),
        "verified_per_person_amount": _F(
            "number",
            "1인당 환산액(원) = 총액 ÷ **문서로 확인된** 인원. 청탁금지 한도처럼 정확한 "
            "인원이 필요한 판정은 이 값을 쓴다 — 확인된 명단이 없으면 null이라 검토로 간다.",
        ),
        "payment_time": _F("time", "결제 시각 `HH:MM`(24시간제)."),
        "payment_method": _F("string", "결제 수단(현재는 법인카드 고정)."),
    },
    "card": {
        "card_type": _F("string", "카드 구분. 귀속·증빙 요구가 이 값으로 갈린다.", "vocab.card_type"),
        "actual_user_recorded": _F(
            "boolean",
            "실사용자가 기록됐는가. 개인 배정 카드는 항상 true, 팀·공용은 본인이 등록해야 true.",
        ),
        "actual_user_is_spender": _F(
            "boolean",
            "카드를 실제로 쓴 사람과 정산을 올린 사람이 같은가. 실사용자 미기록이면 null(모름).",
        ),
    },
    # dept 제거 — 부서명 자체를 비교하는 룰은 없다. 재무회계 여부만 불린으로 남긴다.
    #  v5: `position`(직급) → **`job_title`(직책)으로 교체**. 규정 원문이 "결재 권한 및
    #  법인카드 사용한도는 **직책** 기준으로 부여한다(직급 기준이 아니다)"로 못박고,
    #  별표1도 "직급(사원~전무)과는 무관하다"고 적는다(「직급체계」§1.1 · 별표1 각주).
    #  직급으로는 한도를 정할 수 **없다** — 같은 '이사'라도 부서장 겸직이냐 본부장 대행이냐로
    #  한도가 갈리기 때문이다. 직급(처우 축)은 SoR에 남지만 판정에 올리지 않는다.
    #  `job_title_rank`를 함께 두는 이유: "부서장 이상 승인"을 이름 비교로 쓰면 조직 체계가
    #  바뀔 때 룰을 전부 고쳐야 한다. DSL은 스칼라 비교만 하므로 숫자 축이 필요하다.
    "user": {
        "job_title": _F(
            "string", "지출자의 직책. 결재권·카드한도의 유일한 축이다(직급이 아니다).", "vocab.org",
        ),
        "job_title_rank": _F(
            "integer", "직책 서열. 클수록 상위. 「부서장 이상」을 이름 비교 없이 표현할 때 쓴다.",
        ),
        # 조직 축. v3에서 뺐던 `dept`와 다르다 — 그때는 "부서명을 비교하는 룰이 없다"가
        #  근거였는데, 별표 축(본부별 한도)으로는 실제로 쓰인다. 이름 비교가 아니라
        #  **룩업 키**가 용도다.
        "team": _F("string", "지출자의 소속 팀 이름."),
        "bu": _F("string", "지출자의 소속 본부 이름."),
    },
    # merchant_grade 제거(원천 없음). forbidden은 금지업종 별표 선해소 불린.
    "merchant": {
        "merchant_type": _F(
            "string", "가맹점 업종. 밝히지 못하면 null로 남는다(`기타`로 채우지 않는다).", "vocab.industry",
        ),
        "merchant_info_resolved": _F(
            "boolean",
            "업종 조회에 성공했는가. **예외① null 여부** — 미해소 가드 때문에 "
            "`merchant_type == null`을 룰로 쓸 수 없어 별도 불린이 필요하다.",
        ),
        "industry_confidence": _F(
            "number",
            "업종 판정 신뢰도 0~1. 조회에 성공해도 확신이 낮을 수 있다 — `merchant_info_resolved`"
            "만 보면 「확실한 업종」과 「가까스로 찍은 업종」이 같아 보인다.",
        ),
        "forbidden": _F(
            "boolean",
            "금지업종 별표에 걸리는가(별표 선해소값). 업종 미상이면 null. "
            "**예외② 별표 선해소** — DSL에 룩업 연산자가 없다.",
        ),
    },
    # 세부유형 3종 제거. item_type은 청탁금지 한도 룩업 키라 유지.
    "category": {
        "value": _F("string", "확정된 비용분류.", "vocab.category"),
        "confidence": _F("number", "비용분류 신뢰도 0~1. AI 제안 그대로면 낮다."),
        "item_type": _F(
            "string", "지출 세부유형. 청탁금지 한도(`policy.kickback_limit`) 룩업 키를 겸한다.",
            "vocab.item_type",
        ),
    },
    # 첨부·기재 세분화 7종 제거. "누락"은 대상 필드의 None/0으로 판정한다.
    "evidence": {
        "has_valid_receipt": _F("boolean", "적격증빙(카드매출전표 등)이 첨부됐는가."),
        "expense_purpose_missing": _F(
            "boolean", "지출 목적이 비어 있는가. **역극성 필드** — true가 문제 상황이다.",
        ),
        # 종류별로 나눈 이유: `has_supporting_evidence` 하나로는 "참석자 명단이 필요한
        #  지출인데 명단이 있는가"를 물을 수 없다. 규정이 요구하는 증빙은 종류가 정해져
        #  있고(회의록·명단·출장계획서·계약서), DSL은 목록 포함을 표현하지 못한다.
        "has_meeting_minutes": _F("boolean", "회의록이 첨부됐는가."),
        "has_participant_list": _F("boolean", "참석자 명단이 첨부됐는가."),
        "has_trip_plan": _F("boolean", "출장계획서가 첨부됐는가."),
        "has_contract": _F("boolean", "계약서·견적서가 첨부됐는가."),
    },
    "approval": {
        "pre_approval_obtained": _F("boolean", "사전승인을 받았는가."),
    },
    # 참석자 상세 5종 + kickback_law_category(item_type과 중복) 제거.
    #  ⚠️ **신고값과 확인값을 같은 경로에서 다투게 두지 않는다**(2026-08-23).
    #     예전엔 화면 입력과 첨부 추출이 `participant_count` 하나를 놓고 순위로 겨뤘고,
    #     사람이 적은 값이 늘 이겼다 — 그래서 룰은 "이 인원이 문서로 확인된 것인가"를
    #     **물을 방법이 없었다**. 정확도 요구가 다른 두 판정(식대 1인당 vs 청탁금지 1인당)이
    #     같은 사실을 쓰게 되는 것이 문제의 핵심이었다.
    #     이제 출처가 곧 필드다: 신고값은 화면 입력만, 확인값은 첨부 추출만 채운다.
    "participants": {
        "participant_count": _F(
            "integer",
            "**본인 신고** 참석 인원(화면 입력). 문서로 확인된 값이 아니다 — 승인이 느슨한 "
            "지출(식대·복리후생 등)에만 쓰고, 정확도가 필요하면 `verified_participant_count`를 "
            "쓴다. `0`은 「명단이 없다」, `null`은 「모른다」 — 다른 뜻이다.",
        ),
        "verified_participant_count": _F(
            "integer",
            "**문서로 확인된** 참석 인원(회의록·참석자명단 추출). 첨부가 없거나 판독 신뢰도가 "
            "낮으면 null이다 — 그때 이 값을 참조한 룰은 판정이 검토로 넘어간다(그게 의도다).",
        ),
        "external_participant_count": _F("integer", "**본인 신고** 외부(사외) 참석 인원."),
        "verified_external_count": _F("integer", "**문서로 확인된** 외부(사외) 참석 인원."),
        "has_kickback_law_target": _F("boolean", "청탁금지법 대상자가 참석했는가."),
    },
    # 출장 도메인 미구현 — 숙박 한도 판정에 필요한 3개만 남긴다(별표 축 2 + 비교 대상 1).
    "trip": {
        "trip_type": _F("string", "출장 구분. `policy.lodging_limit` 별표의 축 1."),
        "region_grade": _F("string", "출장 지역등급. `policy.lodging_limit` 별표의 축 2."),
        "lodging_amount_per_night": _F("number", "1박 숙박비(원)."),
    },
    # 분할결제(same_event_multiple_merchants)는 이상탐지(Risk) 영역으로 이관.
    "dining": {
        "includes_alcohol": _F("boolean", "주류가 포함됐는가."),
        "is_secondary_venue": _F("boolean", "2차(차수 이어붙임) 성격의 결제인가."),
    },
    # 집계 윈도우는 조립기 파라미터지 DSL 비교 대상이 아니다 → ctx에서 제외.
    # 승인/지연사유 집계 2종은 원천(승인 모델·사유 판정) 부재로 제거.
    #  ⚠️ 집계 주체는 **카드가 아니라 사람**(실사용자, 없으면 지출자)이다. 비교 대상인
    #     `policy.position_*_limit`이 직책 축이라 사람 기준이어야 뜻이 맞고, 한 사람이
    #     개인·공용 카드를 섞어 쓰면 카드 기준 합계는 한도와 무관한 숫자가 된다.
    "history": {
        "same_vendor_count": _F("integer", "집계 기간 내 같은 가맹점 결제 횟수(본인 기준)."),
        "daily_cumulative_amount": _F("number", "같은 날 본인의 누적 결제액(원). 이 건을 포함한다."),
        "monthly_cumulative_amount": _F("number", "같은 달 본인의 누적 결제액(원). 이 건을 포함한다."),
    },
    # 별표 선해소 스칼라 8종 — 비교 대상이 남아 있는 것만.
    #  ⚠️ `position_*` 접두는 역사적 이름이다. 축은 **직책**(`user.job_title`)이지
    #     직급이 아니다 — 화면 라벨("직책 일일 한도")은 처음부터 맞았고 축 선언만 틀렸었다.
    "policy": {
        "preapproval_threshold": _F("number", "사전승인이 필요해지는 기준액(원). 축: 직책."),
        "position_daily_limit": _F("number", "직책별 1일 한도(원)."),
        "position_monthly_limit": _F("number", "직책별 1개월 한도(원)."),
        "kickback_limit": _F("number", "청탁금지법 1인당 법정 한도(원). 축: 지출 세부유형."),
        "lodging_limit": _F("number", "1박 숙박비 한도(원). 축: 출장구분 × 지역등급."),
        "evidence_threshold": _F("number", "적격증빙이 필수가 되는 기준액(원). 축: 비용분류."),
        "dining_per_person_limit": _F("number", "회식 1인당 한도(원)."),
        "settlement_deadline_days": _F("integer", "정산 제출 기한(영업일)."),
    },
    # 판정 필드(personal_use_suspected·category_specific_*) 제거. 시각·경과일 관찰만 남긴다.
    "derived": {
        "business_days_since_expense": _F("integer", "결제일로부터 지난 영업일 수."),
        "is_weekend": _F(
            "boolean",
            "주말 결제인가. **예외③ 날짜 연산** — DSL에 요일 함수가 없고 원자(요일)도 "
            "스키마에 없어 조합할 수 없다.",
        ),
    },
    # tables는 감사용 원본 스냅샷이며 DSL이 참조하지 않는다 → 고정 목록을 두지 않고
    # 조립기가 실제 사용한 별표만 동적으로 담는다(별표가 늘어도 스키마 변경 없음).
    "tables": {},
    # conflicts도 감사용 동적 섹션이다. 같은 경로에 서로 다른 값이 도착했을 때
    # "무엇을 택하고 무엇을 버렸는지"를 남긴다. DSL은 참조하지 않는다(고정 목록 없음 →
    # `validate_graph_vars`가 conflicts.* 참조를 거부한다).
    "conflicts": {},
    "meta": {
        "tx_id": _F("integer", "거래 id."),
        "settlement_id": _F("integer", "정산 id."),
        "schema_version": _F("integer", "EvalContext 스키마 버전."),
        "builder_version": _F("string", "조립기 버전."),
        "built_at": _F("string", "조립 시각(ISO8601)."),
    },
}

#: 섹션 머리말. 프롬프트에서 필드 묶음의 제목으로 나간다.
SECTION_TITLES: dict[str, str] = {
    "tx": "거래 사실",
    "card": "카드",
    "user": "지출자",
    "merchant": "가맹점",
    "category": "비용분류",
    "evidence": "증빙·기재",
    "approval": "결재·승인",
    "participants": "참석자",
    "trip": "출장",
    "dining": "회식·식사",
    "history": "이력 집계",
    "policy": "규정 임계값(별표 선해소)",
    "derived": "파생 관찰",
    "tables": "감사용 별표 원본(룰 참조 불가)",
    "conflicts": "감사용 출처 충돌 기록(룰 참조 불가)",
    "meta": "메타",
}

EVAL_CONTEXT_SCHEMA_PATHS = frozenset(
    f"{section}.{field}" for section, fields in _SCHEMA_FIELDS.items() for field in fields
)


def schema_catalog(policy_extra: dict[str, FieldSpec] | None = None) -> dict[str, Any]:
    """필드 카탈로그를 JSON 직렬화 가능한 형태로 편다 — `domain/context`의 유일한 창구.

    이 함수가 있어야 `_SCHEMA_FIELDS`의 사본이 밖에 안 생긴다.

    `policy_extra`: 적재된 별표에서 파생된 **동적** `policy.*` 필드
    (`context_builder.policy_field_specs`). 프롬프트에 실리는 목록과 `validate_graph_vars`가
    강제하는 목록은 같아야 하므로, 고정 8칸만 싣지 않는다 — 모델이 쓸 수 있는 임계값을
    모르면 숫자 리터럴을 박는다.
    """
    fields_by_section = dict(_SCHEMA_FIELDS)
    if policy_extra:
        fields_by_section["policy"] = {**fields_by_section["policy"], **policy_extra}
    return {
        "schema_version": EVAL_CONTEXT_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "sections": [
            {
                "section": section,
                "title": SECTION_TITLES.get(section, section),
                "fields": [
                    {
                        "path": f"{section}.{name}",
                        "type": spec.type,
                        "desc": spec.desc,
                        "enum": spec.enum or None,
                    }
                    for name, spec in fields.items()
                ],
            }
            for section, fields in fields_by_section.items()
        ],
    }


class EvalContext(TypedDict):
    tx: dict[str, Any]
    card: dict[str, Any]
    user: dict[str, Any]
    merchant: dict[str, Any]
    category: dict[str, Any]
    evidence: dict[str, Any]
    approval: dict[str, Any]
    participants: dict[str, Any]
    trip: dict[str, Any]
    dining: dict[str, Any]
    history: dict[str, Any]
    policy: dict[str, Any]
    derived: dict[str, Any]
    tables: dict[str, Any]
    conflicts: dict[str, Any]
    meta: dict[str, Any]


def empty_eval_context() -> EvalContext:
    """모든 계약 필드를 가진 null-safe 컨텍스트를 만든다."""
    return {section: {field: None for field in fields} for section, fields in _SCHEMA_FIELDS.items()}  # type: ignore[return-value]


def validate_graph_vars(graph: Any, allowed_paths: frozenset[str] | None = None) -> set[str]:
    """그래프/스냅샷의 모든 조건 경로 중 허용 목록에 없는 경로를 반환한다.

    기본값은 이 모듈의 **정적 상수**다 — 조회 없이 도는 순수 함수로 남긴다(엔진과 같은
    규율: 판정 계열 코드에 숨은 I/O를 두지 않는다).

    적재된 별표가 만드는 `policy.*`까지 허용하려면 호출부가 `context_builder.allowed_var_paths()`를
    **명시적으로** 넘긴다. ACTIVE 전환 게이트(`services.activate`)가 그렇게 한다 — 고객이 올린
    규정의 새 별표를 참조하는 룰이 승인될 수 있어야 하기 때문이다. 사실 경로는 어느 쪽이든
    닫혀 있다(원천 없는 경로를 열면 값이 영원히 null이다).
    """
    from .dsl import extract_vars

    if allowed_paths is None:
        allowed_paths = EVAL_CONTEXT_SCHEMA_PATHS

    nodes = graph.get("nodes", []) if isinstance(graph, dict) else graph.nodes.all()
    missing: set[str] = set()
    for node in nodes:
        condition = node.get("condition", {}) if isinstance(node, dict) else node.condition
        missing.update(extract_vars(condition) - allowed_paths)
    return missing
