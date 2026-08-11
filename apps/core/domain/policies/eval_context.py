"""EvalContext 스키마 계약과 조립 경계 (FR-RA-08).

실제 facts 조립은 이 모듈만 ORM/외부 조회를 사용한다. DSL과 엔진은 이 모듈이
반환한 JSON 직렬화 가능한 dict만 읽는다.
"""

from __future__ import annotations

from typing import Any, TypedDict


EVAL_CONTEXT_SCHEMA_VERSION = 3
BUILDER_VERSION = "3.0"

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
_SCHEMA_FIELDS = {
    # 거래 사실 — day_of_week/is_holiday는 derived.is_weekend로 갈음, service_charge_ratio 제외
    "tx": ("amount", "per_person_amount", "payment_time", "payment_method"),
    "card": ("card_type", "actual_user_recorded"),
    # dept 제거 — 부서명 자체를 비교하는 룰은 없다. 재무회계 여부만 불린으로 남긴다.
    "user": ("position", "finance_dept_is_spender", "is_working_hours"),
    # merchant_grade 제거(원천 없음). forbidden은 금지업종 별표 선해소 불린.
    "merchant": ("merchant_type", "merchant_info_resolved", "forbidden"),
    # 세부유형 3종 제거. item_type은 청탁금지 한도 룩업 키라 유지.
    "category": ("value", "confidence", "item_type"),
    # 첨부·기재 세분화 7종 제거. "누락"은 대상 필드의 None/0으로 판정한다.
    "evidence": ("has_valid_receipt", "has_supporting_evidence", "purpose_missing"),
    # 결재선 모델이 없어 단계·사후승인·자기승인 5종 제거. 사전승인 여부만 남긴다.
    "approval": ("pre_approval_obtained",),
    # 참석자 상세 5종 + kickback_law_category(item_type과 중복) 제거.
    "participants": ("participant_count", "external_participant_count", "has_kickback_law_target"),
    # 출장 도메인 미구현 — 숙박 한도 판정에 필요한 3개만 남긴다(별표 축 2 + 비교 대상 1).
    "trip": ("trip_type", "region_grade", "lodging_amount_per_night"),
    # 분할결제(same_event_multiple_merchants)는 이상탐지(Risk) 영역으로 이관.
    "dining": ("includes_alcohol", "is_secondary_venue"),
    # 집계 윈도우는 조립기 파라미터지 DSL 비교 대상이 아니다 → ctx에서 제외.
    # 승인/지연사유 집계 2종은 원천(승인 모델·사유 판정) 부재로 제거.
    "history": ("same_vendor_count", "daily_cumulative_amount", "monthly_cumulative_amount"),
    # 별표 선해소 스칼라 8종 — 비교 대상이 남아 있는 것만.
    "policy": (
        "preapproval_threshold", "position_daily_limit", "position_monthly_limit",
        "kickback_limit", "lodging_limit",
        "evidence_threshold", "dining_per_person_limit", "settlement_deadline_days",
    ),
    # 판정 필드(personal_use_suspected·category_specific_*) 제거. 시각·경과일 관찰만 남긴다.
    "derived": ("business_days_since_expense", "is_late_night", "is_weekend"),
    # tables는 감사용 원본 스냅샷이며 DSL이 참조하지 않는다 → 고정 목록을 두지 않고
    # 조립기가 실제 사용한 별표만 동적으로 담는다(별표가 늘어도 스키마 변경 없음).
    "tables": (),
    "meta": ("tx_id", "settlement_id", "schema_version", "builder_version", "built_at"),
}
EVAL_CONTEXT_SCHEMA_PATHS = frozenset(
    f"{section}.{field}" for section, fields in _SCHEMA_FIELDS.items() for field in fields
)


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
