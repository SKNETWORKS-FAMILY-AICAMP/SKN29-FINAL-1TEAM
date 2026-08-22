"""EvalContext 스키마 계약과 조립 경계 (FR-RA-08).

실제 facts 조립은 이 모듈만 ORM/외부 조회를 사용한다. DSL과 엔진은 이 모듈이
반환한 JSON 직렬화 가능한 dict만 읽는다.
"""

from __future__ import annotations

from typing import Any, NamedTuple, TypedDict


EVAL_CONTEXT_SCHEMA_VERSION = 5
BUILDER_VERSION = "5.0"

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
        "per_person_amount": _F("number", "1인당 환산액(원) = 총액 ÷ 참석 인원. 인원을 모르면 null."),
        "payment_time": _F("time", "결제 시각 `HH:MM`(24시간제)."),
        "payment_method": _F("string", "결제 수단(현재는 법인카드 고정)."),
    },
    "card": {
        "card_type": _F("string", "카드 구분. 귀속·증빙 요구가 이 값으로 갈린다.", "vocab.card_type"),
        "actual_user_recorded": _F(
            "boolean",
            "실사용자가 기록됐는가. 개인 배정 카드는 항상 true, 팀·공용은 본인이 등록해야 true.",
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
        "finance_dept_is_spender": _F("boolean", "지출자가 재무회계 소속인가."),
        "is_working_hours": _F("boolean", "근무시간 내 결제인가."),
    },
    # merchant_grade 제거(원천 없음). forbidden은 금지업종 별표 선해소 불린.
    "merchant": {
        "merchant_type": _F(
            "string", "가맹점 업종. 밝히지 못하면 null로 남는다(`기타`로 채우지 않는다).", "vocab.industry",
        ),
        "merchant_info_resolved": _F("boolean", "업종 조회에 성공했는가."),
        "forbidden": _F("boolean", "금지업종 별표에 걸리는가(별표 선해소값). 업종 미상이면 null."),
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
        "has_supporting_evidence": _F("boolean", "영수증 외 보조 증빙(회의록·명단 등)이 있는가."),
        "expense_purpose_missing": _F(
            "boolean", "지출 목적이 비어 있는가. **역극성 필드** — true가 문제 상황이다.",
        ),
    },
    "approval": {
        "pre_approval_obtained": _F("boolean", "사전승인을 받았는가."),
    },
    # 참석자 상세 5종 + kickback_law_category(item_type과 중복) 제거.
    "participants": {
        "participant_count": _F(
            "integer", "참석 인원. `0`은 「명단이 없다」, `null`은 「모른다」 — 다른 뜻이다.",
        ),
        "external_participant_count": _F("integer", "외부(사외) 참석 인원."),
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
    "history": {
        "same_vendor_count": _F("integer", "집계 기간 내 같은 가맹점 결제 횟수."),
        "daily_cumulative_amount": _F("number", "같은 날 누적 결제액(원)."),
        "monthly_cumulative_amount": _F("number", "같은 달 누적 결제액(원)."),
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
        "is_late_night": _F("boolean", "심야 시간대 결제인가."),
        "is_weekend": _F("boolean", "주말 결제인가."),
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


def schema_catalog() -> dict[str, Any]:
    """필드 카탈로그를 JSON 직렬화 가능한 형태로 편다 — `domain/context`의 유일한 창구.

    이 함수가 있어야 `_SCHEMA_FIELDS`의 사본이 밖에 안 생긴다.
    """
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
            for section, fields in _SCHEMA_FIELDS.items()
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


def validate_graph_vars(graph: Any) -> set[str]:
    """그래프/스냅샷의 모든 조건 경로 중 스키마에 없는 경로를 반환한다."""
    from .dsl import extract_vars

    nodes = graph.get("nodes", []) if isinstance(graph, dict) else graph.nodes.all()
    missing: set[str] = set()
    for node in nodes:
        condition = node.get("condition", {}) if isinstance(node, dict) else node.condition
        missing.update(extract_vars(condition) - EVAL_CONTEXT_SCHEMA_PATHS)
    return missing
