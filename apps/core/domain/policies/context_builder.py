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

    폴백 규칙은 **표마다 다르다**(`PolicyTable.strict_keys`):

    - `strict_keys=False`(기본): 축 값을 몰라도 ``"*"`` 기본값으로 해소한다. 한도표처럼
      **회사 기본값이 의미 있는** 표다. (예: `user.position`이 아직 SoR에 없어 와일드카드로 떨어진다)
    - `strict_keys=True`: **축 값을 모르면 해소하지 않는다**(``None``). 금지업종표처럼
      "모르면 안전하다"고 단정할 수 없는 표다. 업종을 모르는데 `forbidden=False`로 두면
      금지업종을 조용히 통과시키게 된다 — 모르면 모른다고 남겨 가드가 REVIEW로 보내야 한다.

    ※ 축 값을 **알지만** 표에 없는 경우는 두 모드 모두 ``"*"``로 폴백한다
      (금지 목록에 없는 업종 = 금지 아님. 이건 관측 결과이므로 단정해도 된다).
    - 축이 0개인 전역 임계값은 payload가 ``{"value": <스칼라>}`` 형태다.
    """
    node: Any = table.payload
    for axis in table.key_axes or []:
        if not isinstance(node, dict):
            return None
        raw = resolve_path(ctx, axis)
        if raw is None and table.strict_keys:
            return None                       # 키를 모른다 → 해소 금지
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
        # 출처별로 제안만 하고, 충돌 해소는 FactMerger의 규칙이 담당한다.
        merger = FactMerger()
        collect_from_attachments(merger, settlement)   # RANK_EXTRACT
        collect_from_settlement(merger, settlement)    # RANK_SOR / RANK_INPUT
        derive_after_merge(merger)                     # 합쳐진 값에서 산술 파생
        merger.apply(ctx)
        ctx["meta"].update({
            "settlement_id": settlement.pk,
            "tx_id": getattr(getattr(settlement, "transaction", None), "pk", None),
        })
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

# ── 사실 출처 순위 (높을수록 우선) ────────────────────────────────
#   같은 경로에 서로 다른 값이 도착할 수 있다. 예: 회의록은 4명, 참석자명단은 6명,
#   사용자는 9명. 아무 규칙 없이 나중 값이 이기면 **조용한 손실**이 된다.
RANK_EXTRACT = 1   # 첨부 문서 추출 (증빙자료 추출 Agent)
RANK_INPUT = 2     # 화면 입력 — 사람이 확정한 값
RANK_SOR = 3       # SoR 원장에서 직접 나온 사실·산술 파생 (카드 전표 금액·결제시각 등)

ORIGIN_LABEL = {RANK_EXTRACT: "extract", RANK_INPUT: "input", RANK_SOR: "sor"}


class FactMerger:
    """출처가 다른 사실을 하나의 EvalContext로 합치며 **충돌을 기록**한다.

    규칙:
      1. **높은 순위가 이긴다.** 값이 다르면 진 쪽을 충돌로 기록한다(판정은 이긴 값으로 진행).
      2. **같은 순위에서 값이 다르면 어느 쪽도 쓰지 않는다.** 우리는 진실을 모르므로
         ``None``으로 남기고 충돌을 기록한다 → 미해소 가드가 `REVIEW`로 보낸다.
         (두 문서가 4명/6명이라고 하면 "둘 중 아무거나"가 아니라 "사람이 봐야 한다"가 맞다)
      3. ``None``(모름)은 아무것도 덮지 않는다.

    충돌 이력은 ``ctx["conflicts"]``에 남아 `rule_hits` 스냅샷으로 보존된다(감사·검토 화면).
    """

    def __init__(self) -> None:
        self._value: dict[str, Any] = {}
        self._rank: dict[str, int] = {}
        self._origin: dict[str, str] = {}
        self._contested: set[str] = set()
        self.conflicts: dict[str, dict[str, Any]] = {}

    def offer(self, path: str, value: Any, rank: int, origin: str) -> None:
        if value is None:                                    # 규칙 3
            return
        previous_rank = self._rank.get(path)

        if previous_rank is None:
            self._store(path, value, rank, origin)
            return

        if rank > previous_rank:                             # 규칙 1 — 새 값이 이긴다
            if path in self._contested or self._value.get(path) != value:
                self._record(path, kept=value, kept_from=origin,
                             dropped_value=self._value.get(path),
                             dropped_from=self._origin.get(path),
                             resolution=f"{ORIGIN_LABEL[rank]}_wins")
            self._contested.discard(path)
            self._store(path, value, rank, origin)
            return

        if rank < previous_rank:                             # 규칙 1 — 기존 값이 이긴다
            if self._value.get(path) != value:
                self._record(path, kept=self._value.get(path), kept_from=self._origin.get(path),
                             dropped_value=value, dropped_from=origin,
                             resolution=f"{ORIGIN_LABEL[previous_rank]}_wins")
            return

        # 동순위 — 값이 다르면 어느 쪽도 신뢰할 수 없다 (규칙 2)
        if self._value.get(path) != value:
            self._record(path, kept=None, kept_from=None,
                         dropped_value=value, dropped_from=origin,
                         resolution="dropped_as_unknown")
            self._contested.add(path)
            self._value[path] = None

    def _store(self, path: str, value: Any, rank: int, origin: str) -> None:
        self._value[path] = value
        self._rank[path] = rank
        self._origin[path] = origin

    def _record(self, path: str, *, kept, kept_from, dropped_value, dropped_from, resolution) -> None:
        entry = self.conflicts.setdefault(
            path, {"kept": kept, "kept_from": kept_from, "resolution": resolution, "dropped": []}
        )
        entry.update({"kept": kept, "kept_from": kept_from, "resolution": resolution})
        entry["dropped"].append({"value": dropped_value, "from": dropped_from})

    def resolved(self, path: str) -> Any:
        """지금까지 합쳐진 값(동순위 충돌이면 None)."""
        return self._value.get(path)

    def apply(self, ctx: dict[str, Any]) -> None:
        from .eval_context import EVAL_CONTEXT_SCHEMA_PATHS

        for path, value in self._value.items():
            if path not in EVAL_CONTEXT_SCHEMA_PATHS:
                continue
            section, name = path.split(".", 1)
            ctx[section][name] = value
        ctx["conflicts"].update(self.conflicts)


def collect_from_attachments(merger: FactMerger, settlement) -> None:
    """첨부 문서에서 추출된 사실을 제안한다(`RANK_EXTRACT`).

    **문서끼리도 충돌한다.** 회의록은 4명, 참석자명단은 6명일 수 있다. 예전에는 나중 값이
    조용히 이겼지만, 지금은 동순위 불일치라 어느 쪽도 쓰지 않고 충돌로 기록한다(→ REVIEW).
    """
    ordered = settlement.attachments.filter(extraction_status="DONE").order_by("extracted_at", "id")
    for attachment in ordered:
        origin = f"attachment:{attachment.pk}({attachment.kind})"
        for path, value in (attachment.extracted or {}).items():
            merger.offer(path, value, RANK_EXTRACT, origin)


def collect_from_settlement(merger: FactMerger, settlement) -> None:
    """정산·거래에서 확보 가능한 사실을 제안한다.

    두 순위로 나뉜다:
      · `RANK_SOR`  — 원장에서 직접 나오는 사실(카드 전표 금액·결제시각·영수증 매칭 등).
                      추출값이 달라도 원장이 이긴다(영수증 금액 불일치는 충돌로 기록된다).
      · `RANK_INPUT`— 사람이 화면에서 채운 판정 컬럼. 비어 있으면(None) 제안하지 않는다.
    """
    tx = getattr(settlement, "transaction", None)
    ts = timezone.localtime(tx.ts) if tx is not None and tx.ts else None
    card = getattr(tx, "card", None) if tx is not None else None
    sor = lambda path, value: merger.offer(path, value, RANK_SOR, "sor")          # noqa: E731
    typed = lambda path, value: merger.offer(path, value, RANK_INPUT, "input")    # noqa: E731

    # ── SoR 원장 사실
    sor("tx.amount", int(tx.amount) if tx is not None else None)
    sor("tx.payment_time", ts.strftime("%H:%M") if ts else None)
    sor("tx.payment_method", "법인카드")
    if card is not None:
        sor("card.card_type", card.card_type or None)
        # 개인카드는 소유자가 곧 사용자라 실사용자 기록이 늘 성립한다(공용·팀 카드에서만 물어본다).
        if card.card_type in SHARED_CARD_TYPES:
            typed("card.actual_user_recorded", settlement.actual_user_recorded)
        else:
            sor("card.actual_user_recorded", True)
    sor("category.value", settlement.category or None)
    sor("category.confidence", 0.5 if settlement.ai_suggested else 0.95)
    industry = settlement.merchant_industry or None
    sor("merchant.merchant_type", industry)
    sor("merchant.merchant_info_resolved", bool(industry))   # 업종 확인 실패는 관측 결과(False)
    sor("evidence.has_valid_receipt",
        bool(tx is not None and tx.receipts.exclude(status="MISSING").exists()))
    sor("evidence.expense_purpose_missing", not bool(settlement.purpose))
    sor("evidence.has_supporting_evidence",
        settlement.attachments.exclude(kind="RECEIPT").exists())
    sor("derived.is_late_night", bool(ts and (ts.hour >= 22 or ts.hour < 6)))
    sor("derived.is_weekend", bool(ts and ts.weekday() >= 5))

    # ── 화면 입력 (비었으면 제안하지 않는다 → 추출값이 살아남는다)
    typed("category.item_type", settlement.item_type or None)
    typed("approval.pre_approval_obtained", settlement.pre_approved)
    typed("participants.participant_count", settlement.headcount)
    typed("participants.external_participant_count", settlement.external_headcount)
    typed("participants.has_kickback_law_target", settlement.kickback_target)
    typed("dining.is_secondary_venue", settlement.is_secondary_venue)
    typed("dining.includes_alcohol", settlement.includes_alcohol)


def derive_after_merge(merger: FactMerger) -> None:
    """합쳐진 값에서 산술 파생을 만든다 — **원천이 정해진 뒤에** 계산해야 한다.

    `tx.per_person_amount`를 정산 컬럼에서 미리 계산하면, 인원이 첨부에서만 온 경우
    `None`으로 덮어써 추출값을 지운다(이전 구현의 결함). 여기서 합쳐진 인원으로 계산한다.
    """
    amount = merger.resolved("tx.amount")
    count = merger.resolved("participants.participant_count")
    if amount is not None and count:
        merger.offer("tx.per_person_amount", int(amount) // int(count), RANK_SOR, "derived")
