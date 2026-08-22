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

from domain.transactions import industry as industry_vocab

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

# 조립기가 직접 쓰는 파라미터 표 — `ctx.policy`에 올리지 않는다(DSL 비교 대상이 아니다).
NON_POLICY_TABLES: frozenset[str] = frozenset({"history_window_table"})

#: 표 key → `ctx.policy` 필드명. `RESOLVERS`의 역방향이다 — 표 키에서 기계적으로 못 뽑는
#  이름(`daily_limit_table` → `position_daily_limit`)만 여기 명시로 남는다.
_EXPLICIT_FIELD: dict[str, str] = {table_key: field for field, table_key in RESOLVERS.items()}


def _payload_leaves(node: Any, depth: int) -> list[Any]:
    """축을 `depth`번 따라간 자리의 값들. 축 선언과 payload 깊이가 어긋나면 빈 목록."""
    if depth <= 0:
        return [node]
    if not isinstance(node, dict):
        return []
    out: list[Any] = []
    for child in node.values():
        out.extend(_payload_leaves(child, depth - 1))
    return out


def _exposes_scalar(table: PolicyTable) -> bool:
    """이 표가 `ctx.policy.*`에 올릴 **스칼라**를 내놓는가.

    DSL은 스칼라 비교만 하므로 리프가 목록·중첩인 표(예: 분류별 필요증빙)는 올리지 않는다.
    올려두면 룰이 비교할 수 없는 값을 자신 있게 참조하고, 그 결과는 에러가 아니라 조용한
    거짓이 된다.
    """
    axes = list(table.key_axes or [])
    if not axes:
        leaves = [table.payload.get("value")] if isinstance(table.payload, dict) else []
    else:
        leaves = _payload_leaves(table.payload, len(axes))
    return bool(leaves) and all(isinstance(v, (bool, int, float, str)) for v in leaves)


def policy_fields(tables: dict[str, PolicyTable] | None = None) -> dict[str, str]:
    """`ctx.policy.<필드>` → 별표 key. **적재된 표에서 파생한다.**

    고정 8칸이 아닌 이유: 고객이 자사 규정을 올려 새 별표가 들어오면 그 임계값이 곧바로
    룰이 쓸 수 있는 변수가 되어야 한다. 표 키에서 `_table`을 떼어 이름을 만들고,
    `RESOLVERS`는 이제 **이름 override**로만 남는다(하위호환 — 기존 그래프의 조건이
    `policy.position_daily_limit`을 참조하고 있다).

    제외 셋: 조립기 전용 파라미터(`NON_POLICY_TABLES`) · 이미 `policy` 밖 자리를 차지한 표
    (`DERIVED_FROM_TABLE`, 금지업종 → `merchant.forbidden`) · 스칼라를 안 내놓는 표.
    """
    tables = load_tables() if tables is None else tables
    claimed = set(DERIVED_FROM_TABLE.values()) | NON_POLICY_TABLES
    fields = dict(RESOLVERS)          # 명시 이름이 먼저 자리를 잡는다
    for key in sorted(tables):
        if key in claimed or key in _EXPLICIT_FIELD:
            continue
        if not _exposes_scalar(tables[key]):
            continue
        name = key.removesuffix("_table")
        if name in fields:            # 이름 충돌 — 명시 매핑이 이긴다(조용히 덮지 않는다)
            continue
        fields[name] = key
    return fields


def allowed_var_paths(tables: dict[str, PolicyTable] | None = None) -> frozenset[str]:
    """룰 조건이 참조할 수 있는 경로 — 정적 사실 ∪ **지금 적재된 별표가 만드는 `policy.*`**.

    사실은 닫고 임계값은 여는 이유는 **출처가 다르기 때문**이다. 사실은 SoR·첨부 추출에서
    오므로 경로만 늘리면 값이 영원히 null이지만(룰은 만들어지는데 판정은 전건 강등된다),
    `policy.*`는 별표에서 오므로 표가 적재된 순간 조립기가 **자동으로** 채운다.
    """
    from .eval_context import EVAL_CONTEXT_SCHEMA_PATHS

    return EVAL_CONTEXT_SCHEMA_PATHS | {f"policy.{name}" for name in policy_fields(tables)}


def policy_field_specs(tables: dict[str, PolicyTable] | None = None) -> dict[str, Any]:
    """동적 `policy.*` 필드의 프롬프트용 설명 — `{필드: FieldSpec}`.

    정적 8종은 `eval_context._SCHEMA_FIELDS`가 손으로 쓴 설명을 갖고 있으므로 건드리지
    않는다. 새로 들어온 표는 우리가 설명을 쓸 수 없으니 **표 제목**이 가장 정확한 한 줄이다.
    """
    from .eval_context import FieldSpec

    tables = load_tables() if tables is None else tables
    specs: dict[str, Any] = {}
    for name, key in policy_fields(tables).items():
        if name in RESOLVERS:
            continue
        table = tables.get(key)
        title = (table.title if table and table.title else key).strip()
        specs[name] = FieldSpec("number", f"{title} (별표 선해소값).")
    return specs


def check_table_axes(tables: dict[str, PolicyTable] | None = None) -> dict[str, list[str]]:
    """적재된 별표의 축 중 **EvalContext 스키마에 없는 것**을 찾아 돌려준다.

    축이 스키마에 없으면 `resolve_path`가 항상 None을 돌려주고, `strict_keys=False`인 표는
    `"*"`로 조용히 폴백한다 — 값도 나오고 에러도 플래그도 없어서 그 표가 축을 잃은 걸
    아무도 모른다. `check_table_keys()`가 payload의 **값**을 대조한다면 이쪽은 **축 이름**을
    본다(코드 상수가 아니라 DB 행을 보므로, 시드가 낡아 생긴 드리프트도 잡힌다).
    """
    from .eval_context import EVAL_CONTEXT_SCHEMA_PATHS

    tables = load_tables() if tables is None else tables
    bad: dict[str, list[str]] = {}
    for key, table in sorted(tables.items()):
        unknown = [a for a in (table.key_axes or []) if a not in EVAL_CONTEXT_SCHEMA_PATHS]
        if unknown:
            bad[key] = unknown
    return bad


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

    채우는 필드 목록은 `policy_fields(tables)`가 정한다 — **적재된 표에서 파생**하므로
    고객이 올린 새 별표도 코드 변경 없이 여기로 들어온다.

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

    for field, table_key in policy_fields(tables).items():
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
        apply_facts(ctx, facts, allowed_var_paths(tables))

    ctx["meta"].update({
        "schema_version": EVAL_CONTEXT_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "built_at": timezone.localtime().isoformat(timespec="seconds"),
    })
    return ctx, unresolved


def apply_facts(
    ctx: dict[str, Any], facts: dict[str, Any], allowed: frozenset[str] | None = None,
) -> dict[str, Any]:
    """``{"tx.amount": 500000}`` 형태의 dot-path facts를 컨텍스트에 얹는다.

    허용 경로는 룰 조건과 **같은 집합**이다(`allowed_var_paths`) — 검증셋이 "만약 한도가
    X라면"을 시험하려면 룰이 참조할 수 있는 임계값은 오버라이드도 가능해야 한다. 이미
    별표를 로드해 둔 호출부는 `allowed`를 넘겨 재조회를 아낀다.

    스키마에 없는 경로는 조용히 버린다(화면이 임의 키를 보내도 판정이 깨지지 않도록).
    """
    allowed = allowed_var_paths() if allowed is None else allowed

    for path, value in (facts or {}).items():
        if path not in allowed:
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


# 저신뢰 추출값은 판정에 넣지 않는다(`_context/evidence-extraction-agent.md` §6 결정 2) —
# "적용하되 표시"는 저신뢰 오추출이 자동 통과를 만들 수 있어, 이 프로젝트의 원칙(사람 확정·
# 조용한 실패 금지)에 비추면 미달은 미해소로 남겨 REVIEW로 보내는 쪽이 일관된다. 값 자체는
# `Attachment.extracted`에 그대로 남아 S-03에서 "저신뢰라 반영 안 됨"으로 보여줄 수 있다.
ATTACHMENT_CONFIDENCE_THRESHOLD = 0.6


def collect_from_attachments(merger: FactMerger, settlement) -> None:
    """첨부 문서에서 추출된 사실을 제안한다(`RANK_EXTRACT`).

    **문서끼리도 충돌한다.** 회의록은 4명, 참석자명단은 6명일 수 있다. 예전에는 나중 값이
    조용히 이겼지만, 지금은 동순위 불일치라 어느 쪽도 쓰지 않고 충돌로 기록한다(→ REVIEW).
    """
    ordered = settlement.attachments.filter(extraction_status="DONE").order_by("extracted_at", "id")
    for attachment in ordered:
        origin = f"attachment:{attachment.pk}({attachment.kind})"
        confidence = attachment.field_confidence or {}
        for path, value in (attachment.extracted or {}).items():
            if confidence.get(path, 1.0) < ATTACHMENT_CONFIDENCE_THRESHOLD:
                continue
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
    # 직책 — 조직 마스터에서 온다(문서 검색이 아니라). 결재권·카드한도의 유일한 축이다
    #  (「직급체계」§1.1). **직급은 올리지 않는다** — 처우 축이라 판정 근거가 될 수 없다.
    #  미지정이면 `None`(모름)이라 별표가 와일드카드 기본값(=비직책자 한도)으로 해소된다.
    spender = settlement.submitted_by
    job_title = getattr(spender, "job_title", None) if spender is not None else None
    sor("user.job_title", job_title.name if job_title else None)
    sor("user.job_title_rank", job_title.rank if job_title else None)
    sor("category.value", settlement.category or None)
    sor("category.confidence", 0.5 if settlement.ai_suggested else 0.95)
    # 업종은 저장값을 그대로 올리지 않고 **정본 어휘로 접어서** 올린다(`transactions.industry`).
    #  룰·금지업종 별표가 이 표기로 비교하기 때문이고, 옛 데이터(`한식`·`서점` 등)와 외부에서
    #  들어온 자유 표기도 같은 자리에서 흡수된다. 접히지 않으면 `None`(모름)이다 —
    #  `기타`로 밀면 금지업종 별표가 `"*"→False`로 폴백해 확인 안 한 걸 안전하다고 단정한다.
    industry_label = industry_vocab.canonical_label(
        settlement.merchant_industry_code or settlement.merchant_industry
    ) or None
    sor("merchant.merchant_type", industry_label)
    sor("merchant.merchant_info_resolved", bool(industry_label))   # 업종 확인 실패는 관측 결과(False)
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
