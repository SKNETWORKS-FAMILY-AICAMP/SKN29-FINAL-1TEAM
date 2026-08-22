"""적재된 문서를 **한 번 읽고 갈라주는** 단계 — 조항 분류 + 별표 추출.

    파싱 → 청킹 → 임베딩 → 적재 ─► **triage** ─► 룰 자동생성 트리거
                                     ├ 조항: 규정/안내/별표참조 + 룰 생성 우선순위
                                     └ 별표: PolicyTable 후보(승인 대기)

## 왜 필요한가

적재만 하면 담당자 화면에 조항 수십 개가 **같은 무게로** 늘어선다. 「목적」·「정의」·
「시행일」까지 하나씩 열어보게 되고, 정작 한도·금지 같은 규칙이 될 조항이 그 사이에 묻힌다.
그리고 별표(한도표)는 조에 속하지 않아 조항 목록에 아예 뜨지 않았다 — 임계값의 원천인데
화면에서 보이지도 않았다.

## 분류는 제안이지 차단이 아니다

`SKIP`으로 분류된 조항에서도 사람이 룰을 만들 수 있다(core `clause_generate_rule`).
모델이 못 알아본 규칙이 반드시 있고, 통로가 없으면 분류가 틀린 순간 그 조항은 영영
룰이 되지 못한다.

## 범위 — 회사 규정만

`policy_docs`(REGULATION)에만 돌린다. 법령(`tax_refs`)은 조항이 수백 개인데 **우리 회사의
규칙이 아니라 참조 근거**라, 전수 LLM 분류는 비용만 들고 룰 생성 대상도 아니다. 조직도
(`org_docs`)는 판정이 검색조차 하지 않는다. 건너뛴 사실은 결과에 남긴다(조용한 누락 금지).

## 실패는 적재를 실패시키지 않는다

분류가 없으면 화면이 예전처럼 조항을 평평하게 보여줄 뿐이다. 적재 자체는 이미 끝났고
문서는 검색된다 — 룰 트리거와 같은 판단(`rule_trigger` 모듈 docstring).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: 이 컬렉션만 분류한다. 나머지는 건너뛴 사실만 남긴다.
TRIAGE_COLLECTIONS = frozenset({"policy_docs"})

#: 한 번에 넘길 조항 수. 너무 크면 뒤쪽 조항 판단이 뭉개지고, 너무 작으면 호출이 늘어난다.
CLAUSE_BATCH = 12
#: 조항 본문은 앞부분만 넘긴다 — 판단에 필요한 건 요건·한도가 나오는 도입부다.
CLAUSE_BODY_LIMIT = 900
#: 별표 표 원문은 통째로 넘겨야 한다(값을 뽑는 게 목적이라 자르면 그 행이 사라진다).
#  다만 무한정 넘길 수는 없어 상한을 둔다 — 넘으면 그 표는 사람이 직접 만든다.
TABLE_TEXT_LIMIT = 6000

MODEL = "gpt-4o-mini"

VALID_KINDS = {"RULE", "INFO", "ANNEX"}
VALID_PRIORITIES = {"AUTO", "P1", "P2", "P3", "SKIP"}


@dataclass
class TriageResult:
    ran: bool = False
    skipped_reason: str = ""
    clause_count: int = 0
    table_count: int = 0
    auto_count: int = 0
    error: str = ""
    #: articleLabel → {triageKind, triagePriority, triageReason, triageSummary}
    clauses: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: core `_replace_table_proposals`가 그대로 받는 모양
    tables: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ran": self.ran, "skippedReason": self.skipped_reason,
            "clauseCount": self.clause_count, "tableCount": self.table_count,
            "autoCount": self.auto_count, "error": self.error,
        }


# ─────────────────────────────────────────────────────────── 조항 분류

_CLAUSE_SYSTEM = """당신은 회사의 법인카드 정산 규정을 읽고, 각 조항이 **자동 판정 규칙으로
만들 수 있는지**를 가려내는 검토자입니다.

분류(kind):
- RULE: 판정 가능한 요건이 있다 — 한도·금지·필수 증빙·승인 요건·기한 등. 위반 여부를
  거래 사실(금액·업종·인원·증빙 유무 등)로 따질 수 있는 조항.
- INFO: 규칙이 아니다 — 목적·적용범위·용어 정의·시행일·개정이력·문의처·일반 원칙 선언.
- ANNEX: 조항 자체는 값을 말하지 않고 **별표를 참조**한다("별표1에 따른다", "[별표2] 참조").
  이런 조항의 실제 값은 별표에서 온다.

우선순위(priority) — RULE일 때만 의미가 있다:
- AUTO: 지금 바로 자동 생성해도 되는 것. 조건과 임계값이 조항 안에 명확히 있고, 해석 여지가
  거의 없다(예: "1인당 5만원을 초과할 수 없다", "유흥업소에서 사용할 수 없다").
- P1: 중요하고 자주 걸리지만 조건이 여러 개거나 예외가 있어 사람이 확인해야 한다.
- P2: 규칙화는 가능하나 사례가 드물거나 다른 조항과 함께 봐야 한다.
- P3: 규칙화는 되지만 실익이 낮다.
- SKIP: RULE이 아니거나(INFO/ANNEX) 판정에 쓸 사실이 없어 규칙으로 만들 수 없다.

**INFO와 ANNEX는 priority를 SKIP으로 두세요.**

summary는 "무엇을 검사하는 규칙이 될지"를 한 문장으로. RULE이 아니면 비워두세요.
reason은 왜 그렇게 분류했는지 한두 문장. 담당자가 이 줄만 읽고 열어볼지 정합니다.

조항을 지어내지 말고 주어진 것만 분류하세요. 확신이 없으면 낮은 우선순위를 주되,
규칙일 가능성이 있으면 INFO로 버리지 마세요 — 놓친 규칙보다 확인 한 번이 쌉니다."""

_CLAUSE_SCHEMA = {
    "type": "object",
    "properties": {
        "clauses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "kind": {"type": "string", "enum": sorted(VALID_KINDS)},
                    "priority": {"type": "string", "enum": sorted(VALID_PRIORITIES)},
                    "summary": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["label", "kind", "priority", "summary", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["clauses"],
    "additionalProperties": False,
}


def axis_options() -> list[dict[str, Any]]:
    """축 후보 = EvalContext **사실** 경로. core 카탈로그에서 가져온다.

    사본을 만들지 않는 이유는 이 목록이 곧 승인 검사 기준이기 때문이다 — 여기서 보여준
    축이 core에서 거부되면 사람은 왜 막혔는지 알 수 없다(`domain/context`가 프롬프트와
    검증기를 한 객체로 묶은 것과 같은 규율).

    `policy.*`는 그 자체가 별표에서 나온 값이라 다른 별표의 축이 될 수 없고, `tables`·
    `conflicts`·`meta`는 감사용이라 룰도 별표도 참조하지 않는다.

    조회에 실패하면 **빈 목록**이다 — 그러면 축이 전부 걸러져 표는 축 없이 제안되고,
    사람이 승인 화면에서 고른다. 지어낸 축이 통과하는 것보다 낫다.
    """
    from app.context import get_context

    bundle = get_context("rule_generate", {"sections": "eval_context.paths"})
    skip = {"policy", "tables", "conflicts", "meta"}
    return [
        {"path": f["path"], "type": f["type"], "desc": f["desc"]}
        for sec in bundle.data("eval_context.paths").get("sections", [])
        if sec.get("section") not in skip
        for f in sec.get("fields", [])
    ]


def _openai():
    from app.agents.rule_agent_v0.agent import _openai as client
    return client()


def _chat(system: str, user: str, schema: dict, schema_name: str) -> dict[str, Any]:
    resp = _openai().chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": schema_name, "schema": schema, "strict": True},
        },
    )
    return json.loads(resp.choices[0].message.content or "{}")


def classify_clauses(clauses: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """조항 목록 → `{articleLabel: 분류}`. 실패한 배치는 **그 배치만** 비운다.

    한 배치가 실패했다고 전체를 버리면, 조항 60개짜리 문서에서 1건 실패로 59건의 분류가
    함께 사라진다. 분류가 없는 조항은 화면에서 예전처럼 평평하게 보일 뿐이다.
    """
    out: dict[str, dict[str, Any]] = {}
    for start in range(0, len(clauses), CLAUSE_BATCH):
        batch = clauses[start:start + CLAUSE_BATCH]
        listing = "\n\n".join(
            f"[{c['articleLabel']}] {c.get('articleTitle', '')}\n{(c.get('body') or '')[:CLAUSE_BODY_LIMIT]}"
            for c in batch
        )
        try:
            data = _chat(
                _CLAUSE_SYSTEM,
                f"다음 조항들을 분류하세요. label은 대괄호 안 표기를 그대로 쓰세요.\n\n{listing}",
                _CLAUSE_SCHEMA, "clause_triage",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("조항 분류 실패 (batch %d~): %s", start, exc)
            continue

        known = {c["articleLabel"] for c in batch}
        for row in data.get("clauses", []):
            label = str(row.get("label") or "").strip()
            if label not in known:
                continue                      # 지어낸 조항은 버린다
            kind = str(row.get("kind") or "").upper()
            priority = str(row.get("priority") or "").upper()
            if kind not in VALID_KINDS:
                continue
            if priority not in VALID_PRIORITIES:
                priority = "SKIP"
            if kind != "RULE":
                priority = "SKIP"             # 프롬프트가 시켰지만 강제도 한다
            out[label] = {
                "triageKind": kind,
                "triagePriority": priority,
                "triageSummary": str(row.get("summary") or "")[:300],
                "triageReason": str(row.get("reason") or "")[:2000],
            }
    return out


# ─────────────────────────────────────────────────────── 별표 → 임계값 표

_TABLE_SYSTEM = """당신은 회사 규정의 **별표(한도표)** 를 읽고, 정산 판정 엔진이 쓰는
임계값 표로 옮기는 작업을 합니다.

출력 형태:
- key: 영문 소문자·숫자·밑줄, `_table`로 끝냅니다 (예: daily_limit_table).
  무엇의 표인지 드러나게 짓되 회사명은 넣지 마세요.
- title: 사람이 읽는 표 이름. 원문 표기를 살리세요 (예: "별표1. 직책별 카드 사용한도").
- key_axes: 이 표가 **무엇으로 값을 고르는지**. 아래 [사용 가능한 축] 목록의 경로만
  쓰세요. 목록에 없는 축이 필요하면 key_axes를 비우고 notes에 그 사실을 적으세요.
  표의 행/열 머리글이 곧 축입니다(직책별이면 축 1개, 출장구분×지역등급이면 축 2개).
- payload: 축을 따라 값을 고르는 중첩 객체. 축이 1개면 {"머리글": 값}, 2개면
  {"머리글1": {"머리글2": 값}}. 축이 없으면 {"value": 값}.
  값은 숫자로(원 단위, 쉼표·"원" 제거). 표에 없는 경우를 위한 기본값은 "*" 키에 두세요.
- strict_keys: 축 값을 모를 때 "*" 기본값으로 떨어져도 되면 false. 금지 목록처럼
  "모르면 안전하다"고 단정하면 안 되는 표면 true.
- confidence: 0~1. 셀이 병합돼 있거나 값을 확신 못 하면 낮게 주세요.
- notes: 사람이 확인해야 할 점. 못 옮긴 열, 애매한 머리글, 단위가 불분명한 값.

**이 표가 임계값 표가 아니면**(조직도·서식·절차 흐름 등) is_threshold_table을 false로
두고 나머지는 비우세요. 억지로 만들지 마세요 — 승인하는 사람의 시간을 뺏습니다.

숫자를 지어내지 마세요. 표에 없는 값은 넣지 않습니다."""

_TABLE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_threshold_table": {"type": "boolean"},
        "key": {"type": "string"},
        "title": {"type": "string"},
        "key_axes": {"type": "array", "items": {"type": "string"}},
        "payload_json": {"type": "string"},     # 중첩 자유구조라 문자열로 받는다
        "strict_keys": {"type": "boolean"},
        "confidence": {"type": "number"},
        "notes": {"type": "string"},
    },
    "required": ["is_threshold_table", "key", "title", "key_axes", "payload_json",
                 "strict_keys", "confidence", "notes"],
    "additionalProperties": False,
}


def extract_tables(
    table_chunks: list[Any], axis_options: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """별표·표 청크 → `PolicyTable` 후보 목록.

    축 목록을 프롬프트에 싣는다 — 모델이 축을 지어내면 그 표는 승인 검사에서 막히고
    사람이 다시 고르게 되는데, 애초에 고를 수 있는 것을 보여주면 그 왕복이 없다.
    """
    if not table_chunks:
        return []

    axes_block = "\n".join(f"  {a['path']} ({a['type']}) — {a['desc']}" for a in axis_options)
    out: list[dict[str, Any]] = []

    for chunk in table_chunks:
        body = (chunk.text or "")[:TABLE_TEXT_LIMIT]
        if not body.strip():
            continue
        label = (chunk.article_label or chunk.citation or chunk.chunk_id).strip()
        try:
            data = _chat(
                _TABLE_SYSTEM,
                f"[사용 가능한 축]\n{axes_block}\n\n[표 원문 — {label}]\n{body}",
                _TABLE_SCHEMA, "policy_table_extract",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("별표 추출 실패 chunk=%s: %s", chunk.chunk_id, exc)
            continue

        if not data.get("is_threshold_table"):
            continue
        try:
            payload = json.loads(data.get("payload_json") or "{}")
        except ValueError:
            logger.warning("별표 payload JSON 파싱 실패 chunk=%s", chunk.chunk_id)
            payload = {}
        if not isinstance(payload, dict) or not payload:
            continue

        # 축은 여기서도 거른다 — 프롬프트가 목록을 줬어도 모델은 지어낼 수 있고,
        # 없는 축은 에러 없이 항상 기본값으로 떨어지는 가장 조용한 결함이다.
        allowed = {a["path"] for a in axis_options}
        axes = [a for a in (data.get("key_axes") or []) if a in allowed]
        dropped = [a for a in (data.get("key_axes") or []) if a not in allowed]
        notes = str(data.get("notes") or "")
        if dropped:
            notes = (notes + "\n" if notes else "") + (
                "판정 사실에 없는 축이라 제외했습니다: " + ", ".join(dropped)
                + " — 축을 다시 고르거나, 표에 값이 하나뿐이면 축 없이 두세요."
            )

        out.append({
            "chunkId": chunk.chunk_id,
            "label": label[:100],
            "citation": chunk.citation,
            "pageStart": chunk.page_start,
            "pageEnd": chunk.page_end,
            "rawMarkdown": body,
            "key": str(data.get("key") or "").strip()[:64],
            "title": str(data.get("title") or "").strip()[:200],
            "keyAxes": axes,
            "payload": payload,
            "strictKeys": bool(data.get("strict_keys")),
            "confidence": float(data.get("confidence") or 0.0),
            "notes": notes[:2000],
        })
    return out


# ─────────────────────────────────────────────────────────────── 진입점

def run(
    *, chunks: list[Any], clauses: list[dict[str, Any]], collection: str,
    axis_options: list[dict[str, Any]] | None = None,
) -> TriageResult:
    """적재 직후 호출된다. 예외를 밖으로 던지지 않는다 — 적재는 이미 끝났다."""
    if collection not in TRIAGE_COLLECTIONS:
        return TriageResult(
            skipped_reason=(
                f"`{collection}`은 회사 규정 컬렉션이 아니라 조항 분류를 건너뜁니다 "
                "(법령·조직도는 우리 규칙의 원천이 아닙니다)."
            ),
        )

    result = TriageResult(ran=True)
    try:
        result.clauses = classify_clauses(clauses)
        result.clause_count = len(result.clauses)
        result.auto_count = sum(
            1 for v in result.clauses.values() if v["triagePriority"] == "AUTO"
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("조항 분류 단계 실패")
        result.error = f"조항 분류 실패: {type(exc).__name__}: {exc}"

    try:
        table_chunks = [
            c for c in chunks
            if c.chunk_role != "parent" and (c.chunk_type in ("annex", "table") or c.has_table)
        ]
        result.tables = extract_tables(table_chunks, axis_options or [])
        result.table_count = len(result.tables)
    except Exception as exc:  # noqa: BLE001
        logger.exception("별표 추출 단계 실패")
        result.error = (result.error + " / " if result.error else "") + (
            f"별표 추출 실패: {type(exc).__name__}: {exc}"
        )
    return result
