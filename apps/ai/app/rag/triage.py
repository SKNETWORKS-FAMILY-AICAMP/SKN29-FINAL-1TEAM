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
    #: 규칙 후보(INFO가 아닌 조항) 수. `auto_count`와 함께 보면 선별이 얼마나 좁혔는지 보인다.
    candidate_count: int = 0
    error: str = ""
    #: articleLabel → {triageKind, triagePriority, triageReason, triageSummary}
    clauses: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: core `_replace_table_proposals`가 그대로 받는 모양
    tables: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ran": self.ran, "skippedReason": self.skipped_reason,
            "clauseCount": self.clause_count, "tableCount": self.table_count,
            "autoCount": self.auto_count, "candidateCount": self.candidate_count,
            "error": self.error,
        }


# ─────────────────────────────────────────────────────────── 조항 분류
#
# **두 단계로 나눈 이유** — 조항 하나만 놓고 "지금 자동 생성해도 되나"를 물으면 모델은
# 거의 언제나 "사람이 한 번 보는 게 낫다"고 답한다(실측: 첫 실문서에서 전 조항이
# 「확인 필요」로 나왔다). 비교 대상이 없으면 미루는 쪽이 언제나 안전해 보이기 때문이다.
# 그래서 판단을 갈랐다:
#
#   ① **성격 판별**(`_classify_kinds`) — 이 조항이 지출 사실로 참·거짓을 따질 수 있는가.
#      배치로 돈다. 우선순위는 묻지 않는다.
#   ② **우선순위 선별**(`_rank_candidates`) — ①을 통과한 후보를 **문서 단위로 한자리에
#      놓고** 비교해 순서를 매기고, 위에서 몇 개를 자동 생성으로 고른다.
#
# 문서 단위로 물으면 "무엇이 **더** 급한가"라는 답할 수 있는 질문이 되고, 상한(`AUTO_MAX`)이
# 있으니 후하게 골라도 초안이 쏟아지지 않는다. 자동 생성물은 DRAFT라 사람이 승인해야
# ACTIVE가 되고, 만들어지는 판정은 사람에게 보내는 것뿐이라 틀려도 자동 반려가 없다 —
# 보수적으로 굴 이유가 생각보다 적다.

#: 한 문서에서 자동 생성 대상으로 고를 수 있는 조항 수 상한. 트리거는 이 조항들을 모아
#  질의 하나를 만들어 그래프 **하나**를 생성하므로(`rule_trigger.AUTO_QUERY_CLAUSES`),
#  더 늘려봐야 질의만 넓어진다.
AUTO_MAX = 6
#: 선별 단계에 실어 보낼 후보 수 상한. 넘으면 성격 판별 확신이 높은 순으로 자른다.
RANK_LIMIT = 40

_CLAUSE_SYSTEM = """당신은 회사의 법인카드 정산 규정을 읽고, 각 조항이 **지출 내역으로
참·거짓을 따질 수 있는 요건**을 담고 있는지 가려내는 검토자입니다. 우선순위는 다음
단계에서 따로 정하니 여기서는 성격만 판별하세요.

분류(kind):
- RULE: 판정 가능한 요건이 있다 — 한도·금지·필수 증빙·승인 요건·기한 등. 위반 여부를
  거래 사실(금액·업종·결제시각·인원·증빙 유무·직책 등)로 따질 수 있다.
- ANNEX: 요건은 있는데 **값이 별표에 있다**("별표1에 따른다", "[별표2] 참조").
  별표가 승인되면 그대로 규칙이 되므로 RULE과 같은 자격의 후보다.
- INFO: 규칙이 아니다. 아래 중 하나라도 해당하면 INFO입니다.
    · 목적·적용범위·용어 정의·시행일·개정이력·문의처·일반 원칙 선언
    · 권한·역할을 서술만 하고 지출 요건은 없는 조항("○○팀이 관리·운영한다")
    · 절차·서식 안내(어디에 제출한다, 어떤 양식을 쓴다) — 위반을 거래 사실로 잴 수 없다
    · 다른 규정·지침을 따른다는 위임 조항
  **INFO를 아끼지 마세요.** 안내 조항까지 후보로 올리면 정작 규칙이 될 조항이 그 사이에
  묻힙니다. 애매하면 다음 단계에서 다시 보므로 여기서 놓칠 걱정은 하지 않아도 됩니다.

함께 적을 것:
- has_threshold: 조항 **본문 안에** 숫자·명시적 기준이 있는가(금액·비율·일수·시각·인원).
  "별표에 따른다"는 값이 조항에 없으므로 false입니다.
- certainty: 이 판별에 대한 확신 0~1.
- summary: RULE/ANNEX면 "무엇을 검사하는 규칙이 될지" 한 문장. INFO면 비웁니다.
- reason: 왜 그렇게 봤는지 한두 문장. 담당자가 이 줄만 읽고 열어볼지 정합니다.

조항을 지어내지 말고 주어진 것만 분류하세요."""

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
                    "has_threshold": {"type": "boolean"},
                    "certainty": {"type": "number"},
                    "summary": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["label", "kind", "has_threshold", "certainty", "summary", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["clauses"],
    "additionalProperties": False,
}

_RANK_SYSTEM = f"""당신은 규정 문서 한 건에서 뽑아낸 **규칙 후보 조항 전체**를 놓고,
어떤 것부터 자동 판정 규칙으로 만들지 순서를 정하는 검토자입니다.

후보를 **서로 비교해서** 정하세요. 조항 하나만 보고 "사람이 확인해야 한다"고 미루면
목록 전체가 확인 대기가 되어 아무 도움이 안 됩니다. 순서는 반드시 갈라야 합니다.

우선순위:
- AUTO: 지금 바로 초안을 만든다. 최대 {AUTO_MAX}개까지 고를 수 있고, 후보가 하나라도
  있으면 **적어도 하나는 반드시 AUTO**로 고르세요. 고르는 기준은
  ① 위반이 잦고 금액 영향이 크다 ② 조건이 명확하다(임계값이 조항이나 별표에 있다)
  ③ 판정에 필요한 사실을 시스템이 이미 갖고 있다.
- P1 / P2 / P3: 사람이 확인한 뒤 만든다. 중요도·명확도 순으로 갈라 주세요.
- SKIP: 다른 후보와 **같은 요건을 중복**해 말하거나(그 조항 표기를 reason에 적으세요),
  실제로는 규칙으로 만들 요건이 없을 때만.

만들어지는 것은 **초안(DRAFT)** 이고, 규칙이 내리는 판정은 사람에게 보내는 것(보완요청·
검토)뿐이라 틀려도 자동 반려가 되지 않습니다. 확신이 8할이면 AUTO로 고르세요 — 초안은
룰 콘솔에서 고치면 됩니다.

[판정에 쓸 수 있는 사실] 목록에 없는 값을 요구하는 조항은 AUTO 대신 P2 이하로 두세요
(초안이 만들어져도 검증에서 막힙니다). 목록이 비어 있으면 이 기준은 무시합니다.

reason은 **왜 이 순위인지**를 한 문장으로. 다른 후보와 비교한 근거면 더 좋습니다."""

_RANK_SCHEMA = {
    "type": "object",
    "properties": {
        "ranked": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "priority": {"type": "string", "enum": sorted(VALID_PRIORITIES)},
                    "reason": {"type": "string"},
                },
                "required": ["label", "priority", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["ranked"],
    "additionalProperties": False,
}


def _catalog(skip: set[str]) -> list[dict[str, Any]]:
    """core 카탈로그(`domain/context`)에서 EvalContext 경로를 가져온다 — 사본을 만들지 않는다.

    조회에 실패하면 **빈 목록**이다. 무엇이 비는지는 부르는 쪽 docstring에 적는다.
    """
    from app.context import get_context

    bundle = get_context("rule_generate", {"sections": "eval_context.paths"})
    return [
        {"path": f["path"], "type": f["type"], "desc": f["desc"]}
        for sec in bundle.data("eval_context.paths").get("sections", [])
        if sec.get("section") not in skip
        for f in sec.get("fields", [])
    ]


def fact_paths() -> list[dict[str, Any]]:
    """선별 단계에 실을 **판정 사실 목록**. 축 목록(`axis_options`)과 달리 `policy.*`를 포함한다.

    별표 선해소 임계값도 룰이 비교하는 값이라, 「이 조항이 요구하는 사실을 시스템이 갖고
    있는가」를 물으려면 함께 보여야 한다. 실패하면 빈 목록 — 선별이 사실 가용성을 보지
    않을 뿐, 분류 자체는 그대로 돈다.
    """
    return _catalog({"tables", "conflicts", "meta"})


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
    return _catalog({"policy", "tables", "conflicts", "meta"})


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


def _classify_kinds(clauses: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """① 성격 판별. 실패한 배치는 **그 배치만** 비운다.

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

        known = {c["articleLabel"]: c for c in batch}
        for row in data.get("clauses", []):
            label = str(row.get("label") or "").strip()
            if label not in known:
                continue                      # 지어낸 조항은 버린다
            kind = str(row.get("kind") or "").upper()
            if kind not in VALID_KINDS:
                continue
            out[label] = {
                "kind": kind,
                "title": known[label].get("articleTitle", ""),
                "has_threshold": bool(row.get("has_threshold")),
                "certainty": float(row.get("certainty") or 0.0),
                "summary": str(row.get("summary") or "")[:300],
                "reason": str(row.get("reason") or "")[:1500],
                "order": len(out),
            }
    return out


def _rank_candidates(
    candidates: list[dict[str, Any]], fact_options: list[dict[str, Any]],
) -> dict[str, tuple[str, str]]:
    """② 우선순위 선별 — 후보 전체를 한 번에 보고 `{label: (priority, reason)}`.

    호출이 실패하면 **규칙 기반으로 대신 매긴다**(`_fallback_ranking`). 여기서 빈손으로
    돌아가면 후보가 전부 미분류가 되고 자동 생성이 통째로 멈춘다 — 모델 장애가 "이 문서엔
    만들 규칙이 없다"로 둔갑하는 셈이라 가장 나쁜 실패 방향이다.
    """
    if not candidates:
        return {}

    picked = sorted(candidates, key=lambda c: (-c["certainty"], c["order"]))[:RANK_LIMIT]
    listing = "\n".join(
        f"- [{c['label']}] {c.get('title', '')} · {c['kind']}"
        f"{' · 조항에 임계값 있음' if c['has_threshold'] else ' · 임계값은 별표/외부'}"
        f"\n    {c['summary'] or '(요약 없음)'}"
        for c in sorted(picked, key=lambda c: c["order"])
    )
    facts = "\n".join(f"  {f['path']} ({f['type']}) — {f['desc']}" for f in fact_options)
    user = (
        f"[규칙 후보 {len(picked)}건]\n{listing}\n\n"
        f"[판정에 쓸 수 있는 사실]\n{facts or '(목록을 가져오지 못했습니다 — 이 기준은 무시하세요)'}"
    )
    try:
        data = _chat(_RANK_SYSTEM, user, _RANK_SCHEMA, "clause_ranking")
    except Exception as exc:  # noqa: BLE001
        logger.warning("우선순위 선별 실패 — 규칙 기반으로 대체: %s", exc)
        return _fallback_ranking(candidates)

    known = {c["label"] for c in candidates}
    ranked: dict[str, tuple[str, str]] = {}
    auto = 0
    for row in data.get("ranked", []):
        label = str(row.get("label") or "").strip()
        if label not in known or label in ranked:
            continue
        priority = str(row.get("priority") or "").upper()
        if priority not in VALID_PRIORITIES:
            priority = "P2"
        if priority == "AUTO":
            # 상한은 프롬프트가 아니라 여기서 강제한다 — 모델이 열 개를 고르면 자동 생성
            # 질의가 문서 전체가 되어 검색이 아무것도 좁히지 못한다.
            if auto >= AUTO_MAX:
                priority = "P1"
            else:
                auto += 1
        ranked[label] = (priority, str(row.get("reason") or "")[:400])

    if not ranked:
        logger.warning("우선순위 선별 결과가 비어 있다 — 규칙 기반으로 대체")
        return _fallback_ranking(candidates)

    # 모델이 빠뜨린 후보는 버리지 않고 중간 순위로 남긴다(미분류로 두면 목록 맨 뒤로 밀린다).
    for c in candidates:
        ranked.setdefault(c["label"], ("P2", "선별 응답에 없어 기본 순위로 두었습니다."))

    if auto == 0:
        # 후보가 있는데 AUTO가 하나도 없으면 자동 생성이 통째로 멈춘다(`SKIPPED_NO_AUTO_CLAUSE`).
        # 가장 명확한 후보 하나는 초안을 만들어 본다 — 초안은 사람이 승인해야 ACTIVE가 된다.
        best = max(candidates, key=lambda c: (c["has_threshold"], c["certainty"], -c["order"]))
        ranked[best["label"]] = (
            "AUTO", "선별에서 자동 생성 대상이 없어 가장 명확한 후보를 올렸습니다 — 초안입니다.",
        )
    return ranked


def _fallback_ranking(candidates: list[dict[str, Any]]) -> dict[str, tuple[str, str]]:
    """선별 호출이 실패했을 때의 대체 순서 — 임계값이 조항에 있고 확신이 높은 순.

    모델 없이 매기므로 근거가 얕다. 그 사실을 reason에 적어 화면에서 구분되게 한다.
    """
    ordered = sorted(
        candidates, key=lambda c: (not c["has_threshold"], -c["certainty"], c["order"]),
    )
    note = "선별 호출이 실패해 임계값 유무·확신도로 매긴 임시 순위입니다."
    out: dict[str, tuple[str, str]] = {}
    for i, c in enumerate(ordered):
        if i < 3:
            priority = "AUTO" if c["has_threshold"] else "P1"
        elif i < 10:
            priority = "P2"
        else:
            priority = "P3"
        out[c["label"]] = (priority, note)
    return out


def classify_clauses(
    clauses: list[dict[str, Any]], *, fact_options: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """조항 목록 → `{articleLabel: 분류}`. 성격 판별 → 우선순위 선별 2단.

    `INFO`는 여기서 `SKIP`으로 못박는다 — 선별 단계에 넣지도 않지만, 안내 조항이 1순위로
    큐에 오르면 화면 목록이 곧 신뢰를 잃는다.
    """
    rows = _classify_kinds(clauses)
    candidates = [
        {"label": label, **row} for label, row in rows.items() if row["kind"] != "INFO"
    ]
    ranking = _rank_candidates(candidates, fact_options or [])

    out: dict[str, dict[str, Any]] = {}
    for label, row in rows.items():
        if row["kind"] == "INFO":
            priority, note = "SKIP", ""
        else:
            priority, note = ranking.get(label, ("P2", ""))
        reason = row["reason"]
        if note:
            reason = (reason + " " if reason else "") + f"· 선별: {note}"
        out[label] = {
            "triageKind": row["kind"],
            "triagePriority": priority,
            "triageSummary": row["summary"],
            "triageReason": reason[:2000],
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
    fact_options: list[dict[str, Any]] | None = None,
) -> TriageResult:
    """적재 직후 호출된다. 예외를 밖으로 던지지 않는다 — 적재는 이미 끝났다.

    `axis_options`(별표 축)와 `fact_options`(선별용 사실 목록)를 **밖에서 받는** 이유는
    둘 다 core 왕복이기 때문이다 — 여기서 부르면 분류가 core 가용성에 묶인다.
    """
    if collection not in TRIAGE_COLLECTIONS:
        return TriageResult(
            skipped_reason=(
                f"`{collection}`은 회사 규정 컬렉션이 아니라 조항 분류를 건너뜁니다 "
                "(법령·조직도는 우리 규칙의 원천이 아닙니다)."
            ),
        )

    result = TriageResult(ran=True)
    try:
        result.clauses = classify_clauses(clauses, fact_options=fact_options)
        result.clause_count = len(result.clauses)
        result.auto_count = sum(
            1 for v in result.clauses.values() if v["triagePriority"] == "AUTO"
        )
        result.candidate_count = sum(
            1 for v in result.clauses.values() if v["triageKind"] != "INFO"
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
