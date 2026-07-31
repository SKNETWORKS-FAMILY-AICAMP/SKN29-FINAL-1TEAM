"""EvalContext 스키마 계약과 조립 경계 (FR-RA-08).

실제 facts 조립은 이 모듈만 ORM/외부 조회를 사용한다. DSL과 엔진은 이 모듈이
반환한 JSON 직렬화 가능한 dict만 읽는다.
"""

from __future__ import annotations

from typing import Any, TypedDict


EVAL_CONTEXT_SCHEMA_VERSION = 1
BUILDER_VERSION = "1.0"

# rule-engine-design.md §2.3의 정적 카탈로그. ACTIVE 전환 게이트가 사용한다.
_SCHEMA_FIELDS = {
    "tx": ("amount", "per_person_amount", "payment_time", "day_of_week", "is_holiday", "payment_method", "service_charge_ratio"),
    "card": ("card_type", "actual_user_recorded"),
    "user": ("position", "dept", "finance_dept_is_spender", "is_working_hours"),
    "merchant": ("merchant_type", "merchant_grade", "merchant_info_resolved", "forbidden"),
    "category": ("value", "confidence", "item_type", "entertainment_type", "meal_type", "event_type", "scope"),
    "evidence": ("has_valid_receipt", "has_supporting_evidence", "event_plan_attached", "confirmation_doc_submitted", "purpose_missing", "purpose_is_generic", "participant_list_missing", "vendor_info_missing", "venue_datetime_missing", "project_name_missing", "participant_record_missing"),
    "approval": ("pre_approval_obtained", "pre_approval_level", "post_approval_within_1biz_day", "approver_is_spender_self", "escalated_approval_confirmed", "spender_attended"),
    "participants": ("participant_count", "external_participant_count", "contractor_participant_count", "contractor_regular_communication_purpose", "has_kickback_law_target", "kickback_law_category", "kickback_law_target_status_missing", "participant_includes_former_employee", "family_or_personal_gathering_suspected"),
    "trip": ("trip_type", "region_grade", "lodging_amount_per_night", "flight_class", "flight_duration_hours", "booking_to_trip_gap_months", "during_business_trip", "itinerary_mismatch", "work_end_time", "expense_type", "trip_request_submitted_days_before", "emergency_trip"),
    "dining": ("includes_alcohol", "is_secondary_venue", "same_event_multiple_merchants", "event_scale_payment_method"),
    "history": ("same_vendor_count_3m", "user_post_approval_count_3m", "late_settlement_count_no_reason_3m", "daily_cumulative_amount", "monthly_cumulative_amount"),
    "policy": ("preapproval_threshold", "position_daily_limit", "position_monthly_limit", "kickback_limit", "lodging_limit", "position_required_level", "gift_type", "approver_daily_limit"),
    "derived": ("personal_use_suspected", "business_days_since_expense", "business_days_since_trip_end", "biz_days_over_7", "is_late_night", "is_weekend", "category_specific_deadline_applies", "category_specific_preapproval_rule_exists"),
    "tables": ("daily_limit_table", "monthly_limit_table", "kickback_limit_table", "lodging_limit_table", "pre_approval_threshold_table"),
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
