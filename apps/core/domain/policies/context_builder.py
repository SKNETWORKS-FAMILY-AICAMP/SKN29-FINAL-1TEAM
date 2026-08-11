"""EvalContext 조립기 — `_context/policy-domain.md` §3, 요구사항 FR-RA-08.

**이 모듈만 ORM/외부 조회를 한다.** DSL(`dsl.py`)과 엔진(`engine.py`)은 여기서 나온
JSON 직렬화 가능한 dict만 읽는다.

핵심 동작은 "별표 선해소"다. 룰 명세서에는 ``amount > pre_approval_threshold_table[position]``
같은 **동적 키 룩업**이 나오는데, 이를 DSL이 직접 하면 (a) DSL에 인덱싱 연산자가 필요해지고
(b) 테이블 I/O가 엔진으로 새어든다. 그래서 조립 시점에 이미 알려진 키(직책·출장구분 등)로
룩업을 끝내 ``ctx.policy.*`` **스칼라**로 넣는다. 원본 표는 감사·재현용으로 ``ctx.tables.*``에
그대로 보존한다(DSL 미참조).

이번 범위는 **`policy.*` + `tables.*`** 다. `merchant.*`(MCP)·`history.*`(SoR 집계)는 후속 단계.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from django.db.models import Q
from django.utils import timezone

from .dsl import resolve_path
from .eval_context import BUILDER_VERSION, EVAL_CONTEXT_SCHEMA_VERSION, empty_eval_context
from .models import PolicyTable

WILDCARD = "*"

# ctx.policy.<필드> ← (별표 key, 룩업 축을 못 찾았을 때 쓸 기본 축)
# 축 자체는 PolicyTable.key_axes가 SoT다. 여기서는 "어느 표를 어느 필드로 옮기는가"만 정한다.
RESOLVERS: dict[str, str] = {
    "preapproval_threshold": "pre_approval_threshold_table",
    "position_daily_limit": "daily_limit_table",
    "position_monthly_limit": "monthly_limit_table",
    "kickback_limit": "kickback_limit_table",
    "lodging_limit": "lodging_limit_table",
    "evidence_threshold": "evidence_threshold_table",
    "dining_per_person_limit": "dining_per_person_limit_table",
    "settlement_deadline_days": "settlement_deadline_table",
}

# 별표에서 오지만 `ctx.policy`가 아닌 자리에 들어가는 선해소 값.
# (금지업종 "목록"을 DSL의 `in` 리터럴로 박으면 규정 개정을 못 따라간다 → 불린으로 선해소)
DERIVED_FROM_TABLE: dict[str, str] = {
    "merchant.forbidden": "forbidden_merchant_table",
}


def load_tables(as_of: date | None = None) -> dict[str, PolicyTable]:
    """지출 시점에 유효한 별표를 key당 1개씩 로드한다.

    요청당 **한 번만** 부르고 이후는 메모리 룩업이다(배치 시뮬레이션 N+1 방지).
    개정이 INSERT로 쌓이므로 같은 key에 여러 행이 있을 수 있다 — 유효한 것 중 최신을 고른다.
    """
    as_of = as_of or timezone.localdate()
    rows = (
        PolicyTable.objects.filter(effective_date__lte=as_of)
        .filter(Q(superseded_date__isnull=True) | Q(superseded_date__gt=as_of))
        .order_by("key", "-effective_date")
    )
    latest: dict[str, PolicyTable] = {}
    for row in rows:
        latest.setdefault(row.key, row)      # order_by 덕에 첫 행이 최신
    return latest


def lookup(table: PolicyTable, ctx: dict[str, Any]) -> Any:
    """`key_axes`를 따라 payload를 파고들어 스칼라를 얻는다. 못 찾으면 ``None``.

    - 축 값이 없거나 표에 없는 값이면 ``"*"`` 항목으로 폴백한다
      (예: `user.position`이 아직 SoR에 없어 항상 와일드카드로 떨어진다).
    - 축이 0개인 전역 임계값은 payload가 ``{"value": <스칼라>}`` 형태다.
    """
    node: Any = table.payload
    for axis in table.key_axes or []:
        if not isinstance(node, dict):
            return None
        raw = resolve_path(ctx, axis)
        key = str(raw) if raw is not None else None
        if key is not None and key in node:
            node = node[key]
        elif WILDCARD in node:
            node = node[WILDCARD]
        else:
            return None
    if isinstance(node, dict):
        node = node.get("value")          # 축 없는 전역값
    # 리프가 리스트인 표도 있다(required_evidence_table). dict가 남았다면 축 선언이 잘못된 것이다.
    return None if isinstance(node, dict) else node


def resolve_policy(ctx: dict[str, Any], tables: dict[str, PolicyTable]) -> list[str]:
    """별표를 `ctx.policy.*` 스칼라로 선해소하고 원본을 `ctx.tables.*`에 보존한다.

    Returns: 해소하지 못한 policy 필드 이름들(호출부 로깅용). 엔진의 미해소 가드는
    실제 참조된 것만 보므로, 여기서 못 채워도 그 필드를 안 쓰는 그래프는 영향받지 않는다.
    """
    unresolved: list[str] = []

    def _resolve(table_key: str) -> Any:
        table = tables.get(table_key)
        if table is None:
            return None
        value = lookup(table, ctx)
        if value is not None:
            ctx["tables"][table_key] = table.payload   # 감사용 원본 (DSL 미참조)
        return value

    for field, table_key in RESOLVERS.items():
        value = _resolve(table_key)
        if value is None:
            unresolved.append(field)
        else:
            ctx["policy"][field] = value

    # policy 밖에 들어가는 선해소 값(예: merchant.forbidden)
    for path, table_key in DERIVED_FROM_TABLE.items():
        value = _resolve(table_key)
        if value is None:
            unresolved.append(path)
        else:
            section, name = path.split(".", 1)
            ctx[section][name] = value
    return unresolved


def build_rule_context(
    *,
    settlement=None,
    facts: dict[str, Any] | None = None,
    as_of: date | None = None,
    tables: dict[str, PolicyTable] | None = None,
    base: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """판정용 EvalContext를 조립한다.

    Args:
        settlement: 정산 인스턴스(있으면 tx/category/evidence 계열을 채운다).
        facts: dot-path 오버라이드(검증셋 화면 입력). **선해소 이후** 얹혀 상위로 이긴다
               — "만약 한도가 X라면"을 시험할 수 있어야 하기 때문이다.
        as_of: 별표 유효일 기준. 기본은 오늘, 정산이 있으면 그 결제일.
        tables: 미리 로드한 별표(배치에서 재사용). 없으면 여기서 로드한다.
        base: 이미 부분 조립된 컨텍스트(없으면 빈 컨텍스트에서 시작).

    Returns: ``(eval_context, unresolved_policy_fields)``
    """
    ctx = base if base is not None else empty_eval_context()
    if settlement is not None:
        # 우선순위: 첨부 추출 < 화면 입력(정산 컬럼). 사람이 확정한 값이 추출값을 이긴다.
        apply_facts(ctx, facts_from_attachments(settlement))
        _fill_from_settlement(ctx, settlement)
        as_of = as_of or _expense_date(settlement)

    tables = tables if tables is not None else load_tables(as_of)
    unresolved = resolve_policy(ctx, tables)

    if facts:
        apply_facts(ctx, facts)

    ctx["meta"].update({
        "schema_version": EVAL_CONTEXT_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "built_at": timezone.localtime().isoformat(timespec="seconds"),
    })
    return ctx, unresolved


def apply_facts(ctx: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    """``{"tx.amount": 500000}`` 형태의 dot-path facts를 컨텍스트에 얹는다.

    스키마에 없는 경로는 조용히 버린다(화면이 임의 키를 보내도 판정이 깨지지 않도록).
    """
    from .eval_context import EVAL_CONTEXT_SCHEMA_PATHS

    for path, value in (facts or {}).items():
        if path not in EVAL_CONTEXT_SCHEMA_PATHS:
            continue
        section, field = path.split(".", 1)
        ctx[section][field] = value
    return ctx


def _expense_date(settlement) -> date | None:
    tx = getattr(settlement, "transaction", None)
    ts = getattr(tx, "ts", None)
    return timezone.localtime(ts).date() if ts else None


SHARED_CARD_TYPES = ("SHARED", "TEAM")


def _set_known(section: dict[str, Any], field: str, value: Any) -> None:
    """값을 알 때만 쓴다. ``None``(모름)으로는 기존 값을 덮지 않는다."""
    if value is not None:
        section[field] = value


def _fill_from_settlement(ctx: dict[str, Any], settlement) -> None:
    """정산·거래에서 확보 가능한 사실만 채운다. 나머지는 None으로 남긴다(모름 계약).

    **거짓을 아는 것과 모르는 것을 구분한다** — 판단 가능한 항목은 반드시 명시값(False 포함)을
    쓰고, 원천이 없는 항목만 None으로 남겨 미해소 가드가 잡게 한다.
    """
    tx = getattr(settlement, "transaction", None)
    ts = timezone.localtime(tx.ts) if tx is not None and tx.ts else None
    card = getattr(tx, "card", None) if tx is not None else None

    ctx["tx"].update({
        "amount": int(tx.amount) if tx is not None else None,
        "payment_time": ts.strftime("%H:%M") if ts else None,
        "payment_method": "법인카드",
        "per_person_amount": settlement.per_person_amount,
    })
    if card is not None:
        ctx["card"]["card_type"] = card.card_type or None
        # 개인카드는 사용자가 곧 소유자라 실사용자 기록이 늘 성립한다(공용·팀 카드에서만 물어본다).
        ctx["card"]["actual_user_recorded"] = (
            settlement.actual_user_recorded
            if card.card_type in SHARED_CARD_TYPES
            else True
        )
    ctx["category"].update({
        "value": settlement.category or None,
        "confidence": 0.5 if settlement.ai_suggested else 0.95,
        "item_type": settlement.item_type or None,
    })
    industry = settlement.merchant_industry or None
    ctx["merchant"].update({
        "merchant_type": industry,
        "merchant_info_resolved": bool(industry),   # 업종을 못 밝혔으면 False(관측 결과)
    })
    ctx["evidence"].update({
        "has_valid_receipt": bool(tx is not None and tx.receipts.exclude(status="MISSING").exists()),
        "purpose_missing": not bool(settlement.purpose),
        "has_supporting_evidence": settlement.attachments.exclude(kind="RECEIPT").exists(),
    })
    # 아래는 사용자가 비워둘 수 있는 입력 컬럼이다. 비었으면(None) **덮어쓰지 않는다** —
    # 첨부 문서에서 추출한 값이 이미 얹혀 있을 수 있고, "모름"으로 그걸 지우면 안 된다.
    _set_known(ctx["approval"], "pre_approval_obtained", settlement.pre_approved)
    _set_known(ctx["participants"], "participant_count", settlement.headcount)
    _set_known(ctx["participants"], "external_participant_count", settlement.external_headcount)
    _set_known(ctx["participants"], "has_kickback_law_target", settlement.kickback_target)
    _set_known(ctx["dining"], "is_secondary_venue", settlement.is_secondary_venue)
    _set_known(ctx["dining"], "includes_alcohol", settlement.includes_alcohol)
    ctx["derived"].update({
        "is_late_night": bool(ts and (ts.hour >= 22 or ts.hour < 6)),
        "is_weekend": bool(ts and ts.weekday() >= 5),
    })
    ctx["meta"].update({
        "settlement_id": settlement.pk,
        "tx_id": tx.pk if tx is not None else None,
    })


def facts_from_attachments(settlement) -> dict[str, Any]:
    """첨부 문서에서 추출된 사실을 dot-path dict로 모은다.

    추출 Agent가 채운 `Attachment.extracted`를 합친다. 같은 경로가 여러 문서에서 나오면
    **더 최근에 추출된 값**이 이긴다(재추출이 이전 추출을 대체한다).
    화면 입력(`Settlement.*` 컬럼)은 사람이 확정한 값이므로 추출값보다 우선한다 —
    호출부가 추출 facts를 먼저 얹고 그 위에 컬럼값을 덮는다.
    """
    merged: dict[str, Any] = {}
    ordered = settlement.attachments.filter(extraction_status="DONE").order_by("extracted_at", "id")
    for attachment in ordered:
        for path, value in (attachment.extracted or {}).items():
            merged[path] = value
    return merged
