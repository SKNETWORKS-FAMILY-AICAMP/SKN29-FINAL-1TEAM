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
import re
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

#: 이 단계가 쓰는 프로파일. **판단이 결과가 되는 자리**라 heavy(`llm_heavy_model`)다 —
#  별표 한 장을 잘못 읽으면 그 값이 모든 정산 판정에 들어간다. 모델 이름은 `app/llm.py`가
#  한 곳에서 알고, env(`LLM_HEAVY_MODEL`)로 바뀐다.
#
#  gpt-4o-mini로 돌던 동안 같은 입력의 결과가 실행마다 달랐다(key 이름·축 선택·스킵 여부).
#  → `.personal/TRIAGE_TABLE_DUMP.md`
PROFILE = "heavy"

#: 별표 key 표기 — core `table_proposals.KEY_RE`의 거울(승인 검사와 같은 기준을
#  추출 시점에 적용해, 승인 화면에서 막히기 전에 모델이 다시 만들게 한다).
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")

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
        #  **값 어휘(`enumValues`)를 함께 싣는다.** 축이 실재하는 경로이기만 하면 통과하던
        #  탓에, payload 키가 그 축의 값으로 나올 수 없는 표기여도(축 `category.value`에
        #  키 「음식물」) 검사를 지나갔다 — 룩업은 매번 `*`로 떨어지고 에러도 로그도 없다.
        {"path": f["path"], "type": f["type"], "desc": f["desc"],
         "values": f.get("enumValues") or []}
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
    #  값 어휘까지 함께 온다(`_catalog`) — 증빙 추출(`vision/document.py`)이 이 목록으로
    #  모델을 제약한다. **별표 축과 증빙 추출이 같은 어휘를 봐야** 서식·표 키·추출값 셋이
    #  한 줄로 꿰인다.
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


def _chat(system: str, user: str, schema: dict, schema_name: str,
          shots: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    """모델 호출 1회. **모델 이름·파라미터 차이는 `app/llm.py`가 안다**(호출부는 역할로 부른다).

    `shots`: (사용자 입력, 모범 출력 JSON) 쌍. 지시문만으로는 안 잡히는 것들 —
    표기 매핑·다열 처리·건너뛰기 판단 — 을 **보여준다.**
    """
    from app import llm

    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for shot_user, shot_answer in shots or []:
        messages.append({"role": "user", "content": shot_user})
        messages.append({"role": "assistant", "content": shot_answer})
    messages.append({"role": "user", "content": user})

    resp = llm.chat(
        PROFILE, messages=messages, timeout=120,
        response_format={"name": schema_name, "schema": schema, "strict": True},
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

# ────────────────────── 별표 → 임계값 표

#: 앞뒤 청크에서 끌어올 문맥 길이. 표만 던지면 「무엇의 한도인지」가 표 밖에 있다 —
#  머리글이 "구분"뿐이고 그게 출장 유형인지 회식 단위인지는 앞 문장이 말한다.
NEIGHBOR_CONTEXT = 400
#: 추출 시도 횟수(최초 호출 포함). 검사에 걸린 문제를 적어 다시 부른다.
TABLE_ATTEMPTS = 2

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
  {"머리글1": {"머리글2": 값}}. **축이 하나라도 있으면 마지막 자리는 숫자입니다** —
  `{"팀": 50000}`이지 `{"팀": {"value": 50000}}`가 아닙니다.
  `value` 키는 **축이 하나도 없을 때만** 씁니다: {"value": 값}.
  값은 숫자로(원 단위, 쉼표·"원" 제거). 표에 없는 경우를 위한 기본값은 "*" 키에 두세요.
  **payload의 중첩 깊이는 key_axes 길이와 반드시 같아야 합니다.**
  축에 「값:」 목록이 붙어 있으면 **payload의 키는 그 목록에 있는 표기여야 합니다.**
  표 머리글이 다르면 뜻이 같은 값으로 바꿔 적으세요 — 머리글이 "음식물"이고 값 목록에
  "식사"가 있으면 키는 "식사"입니다. 어느 값에도 대응되지 않는 행이 있으면 그 축을 쓰지
  말고 key_axes를 비운 뒤 notes에 적으세요.
  **값 목록은 표기를 맞추는 용도이지 채워 넣을 목록이 아닙니다.** 표에 실제로 나온 행만
  담으세요 — 표에 없는 값을 목록에서 가져와 같은 숫자로 채우면 그 축은 아무것도 가르지
  못합니다.
- strict_keys: 축 값을 모를 때 "*" 기본값으로 떨어져도 되면 false. 금지 목록처럼
  "모르면 안전하다"고 단정하면 안 되는 표면 true.
- confidence: 0~1. 셀이 병합돼 있거나 값을 확신 못 하면 낮게 주세요.
- notes: 사람이 확인해야 할 점. 못 옮긴 열, 애매한 머리글, 단위가 불분명한 값.
- comment: 담당자에게 **한국어 두세 문장**으로 설명하세요 — 이 표에서 무엇을 읽었고
  승인 전에 무엇을 눈으로 확인해야 하는지. 전문용어(축·payload·스칼라)는 쓰지 마세요.

**한 표에 값 열이 여러 개면**(예: 일비·식비·숙박비가 한 행에) 그중 **하나만** 고르고
나머지는 notes에 "별도 표로 나눠야 함: …"이라고 적으세요. 판정 엔진은 표 하나에서
값 하나를 꺼내므로, 여러 열을 한 payload에 섞으면 쓸 수 없습니다.

**이 표가 임계값 표가 아니면**(조직도·서식·절차 흐름·승인권자 표 등) is_threshold_table을
false로 두고 **skip_reason에 그 이유를 한국어 한 문장**으로 적으세요. 억지로 만들지
마세요 — 승인하는 사람의 시간을 뺏습니다.

숫자를 지어내지 마세요. 표에 없는 값은 넣지 않습니다."""

_TABLE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_threshold_table": {"type": "boolean"},
        "skip_reason": {"type": "string"},
        "key": {"type": "string"},
        "title": {"type": "string"},
        "key_axes": {"type": "array", "items": {"type": "string"}},
        "payload_json": {"type": "string"},     # 중첩 자유구조라 문자열로 받는다
        "strict_keys": {"type": "boolean"},
        "confidence": {"type": "number"},
        "notes": {"type": "string"},
        "comment": {"type": "string"},
    },
    "required": ["is_threshold_table", "skip_reason", "key", "title", "key_axes",
                 "payload_json", "strict_keys", "confidence", "notes", "comment"],
    "additionalProperties": False,
}


#: 별표 추출 few-shot. **지시문으로 안 잡히던 셋을 보여준다** — ① 표 머리글을 값 어휘로
#  옮기기 ② 값 열이 여러 개일 때 하나만 고르기 ③ 임계값 표가 아닌 것 건너뛰기.
#
#  실측 예시가 아니라 **일반화된 가상 표**다. 실제 규정 문장을 넣으면 모델이 그 회사 값을
#  기억해 다른 문서에도 흘린다(프롬프트가 데이터를 오염시킨다).
_SHOTS: list[tuple[str, str]] = [
    (
        "[사용 가능한 축]\n"
        "  category.item_type (string) — 지출 세부유형\n"
        "      값: 식사 | 선물 | 경조사 | 상품권 | 행사성 | 숙박 | 교통 | 소모품 | 기타\n\n"
        "[문서] 사내복지_운영지침\n"
        "[위치] 제4장 지원 기준 · 별표3 · 항목별 증빙 기준액\n"
        "[앞 문맥] …다음 각 호의 항목은 별표3의 기준액을 초과할 때 적격증빙을 첨부한다.\n\n"
        "[표 원문 — p12]\n"
        "| 항목 | 기준액 |\n|---|---|\n| 식음료 | 30,000원 |\n| 기념품 | 50,000원 |\n"
        "| 경조 화환 | 100,000원 |",
        json.dumps({
            "is_threshold_table": True, "skip_reason": "",
            "key": "item_evidence_threshold_table",
            "title": "별표3. 항목별 증빙 기준액",
            "key_axes": ["category.item_type"],
            "payload_json": json.dumps(
                {"식사": 30000, "선물": 50000, "경조사": 100000}, ensure_ascii=False),
            "strict_keys": False, "confidence": 0.9,
            "notes": "표 머리글을 값 어휘로 옮겼습니다: 식음료→식사, 기념품→선물, 경조 화환→경조사.",
            "comment": "항목별로 적격증빙이 필요해지는 금액입니다. 세 행의 표기를 시스템 어휘로"
                       " 바꿔 담았으니, 원문의 「식음료·기념품·경조 화환」과 같은 뜻이 맞는지"
                       " 확인해 주세요.",
        }, ensure_ascii=False),
    ),
    (
        "[사용 가능한 축]\n"
        "  trip.trip_type (string) — 출장 구분\n      값: 국내당일 | 국내숙박 | 해외\n"
        "  trip.region_grade (string) — 출장 지역등급\n      값: A | B | C\n\n"
        "[문서] 출장관리_내규\n"
        "[위치] 별표1 · 출장 구분·지역별 지급 기준\n\n"
        "[표 원문 — p7]\n"
        "| 구분 | 지역 | 교통비 | 숙박비 | 일비 |\n|---|---|---|---|---|\n"
        "| 해외 | 1급지 | 실비 | 200,000원 | 70,000원 |\n"
        "| 해외 | 2급지 | 실비 | 140,000원 | 50,000원 |",
        json.dumps({
            "is_threshold_table": True, "skip_reason": "",
            "key": "overseas_lodging_limit_table",
            "title": "별표1. 출장 구분·지역별 지급 기준(숙박비)",
            "key_axes": ["trip.trip_type", "trip.region_grade"],
            "payload_json": json.dumps(
                {"해외": {"A": 200000, "B": 140000}}, ensure_ascii=False),
            "strict_keys": False, "confidence": 0.85,
            "notes": "값 열이 셋이라 숙박비만 담았습니다. 별도 표로 나눠야 함: 일비(해외 A 70,000원,"
                     " B 50,000원), 교통비(실비라 임계값 없음)."
                     " 지역 표기 1급지→A, 2급지→B로 옮겼습니다. C급지는 표에 없어 비웠습니다.",
            "comment": "해외출장 숙박비 상한입니다. 한 행에 교통비·숙박비·일비가 함께 있어"
                       " 숙박비만 옮겼고, 일비는 별도 표로 만들어야 합니다. 「1급지/2급지」를"
                       " A/B로 본 것이 맞는지 확인해 주세요.",
        }, ensure_ascii=False),
    ),
    (
        "[사용 가능한 축]\n  user.job_title (string) — 지출자의 직책\n\n"
        "[문서] 지출결의_업무편람\n[위치] 제3장 결재 · 별표5 · 결재 단계별 담당\n\n"
        "[표 원문 — p20]\n"
        "| 단계 | 담당 | 처리 기한 |\n|---|---|---|\n"
        "| 1차 | 기안 부서장 | 2영업일 |\n| 2차 | 재무팀 | 3영업일 |",
        json.dumps({
            "is_threshold_table": False,
            "skip_reason": "결재 단계별 담당과 처리 기한을 적은 절차 표이고, 정산 판정이 비교할"
                           " 금액 임계값이 없습니다.",
            "key": "", "title": "", "key_axes": [], "payload_json": "{}",
            "strict_keys": False, "confidence": 0.95, "notes": "",
            "comment": "결재 절차를 설명하는 표라 판정 임계값으로 만들지 않았습니다."
                       " 처리 기한(2·3영업일)은 금액 기준이 아니라 업무 규칙입니다.",
        }, ensure_ascii=False),
    ),
]


def _groups(table_chunks: list[Any]) -> list[list[Any]]:
    """**같은 별표는 한 덩어리로 묶는다.**

    표는 페이지 경계에서 쪼개진다 — 실측: `출장비_사용규정` 별표2가 A·B등급(5쪽)과
    C등급(6쪽) 두 청크였다. 청크마다 따로 추출하면 **반쪽짜리 표 두 개**가 승인 대기에
    올라온다(C등급만 있는 표는 승인해도 쓸모가 없다). 게다가 머리글이 첫 조각에만 있어
    뒷 조각은 축조차 고를 수 없다.

    묶는 기준은 `parent_chunk_id` — 청커가 같은 조/별표의 조각에 같은 부모를 달아 준다.
    부모가 없는 단독 표(`atomic`)는 혼자 한 그룹이다.
    """
    buckets: dict[str, list[Any]] = {}
    for c in table_chunks:
        buckets.setdefault(c.parent_chunk_id or c.chunk_id, []).append(c)
    for group in buckets.values():
        group.sort(key=lambda c: (c.page_start or 0, c.chunk_id))
    return list(buckets.values())


def _context_block(group: list[Any], by_id: dict[str, Any]) -> str:
    """표 앞뒤의 맥락. **표 안에 없는 것이 표의 의미를 정한다.**

    머리글이 "구분"뿐이면 그게 출장 유형인지 회식 단위인지 표만 봐서는 모른다 — 문서명·
    장·조 제목과 바로 앞 문장이 그걸 말한다. 뒤 문장은 단위·예외("천원 단위", "다만 …는
    제외")가 붙는 자리라 함께 넣는다.
    """
    head = group[0]
    lines = [f"[문서] {head.doc_name}"]
    where = " · ".join(x for x in (head.chapter_title, head.article_label, head.article_title) if x)
    if where:
        lines.append(f"[위치] {where}")
    if head.citation:
        lines.append(f"[인용] {head.citation}")
    if head.header:
        lines.append(f"[계층] {head.header}")

    prev = by_id.get(head.prev_chunk_id or "")
    if prev is not None and prev.chunk_role != "parent" and prev.text:
        lines.append(f"[앞 문맥] …{prev.text[-NEIGHBOR_CONTEXT:].strip()}")
    nxt = by_id.get(group[-1].next_chunk_id or "")
    if nxt is not None and nxt.chunk_role != "parent" and nxt.text:
        lines.append(f"[뒤 문맥] {nxt.text[:NEIGHBOR_CONTEXT].strip()}…")
    return "\n".join(lines)


#: 「5만원」·「3천원」처럼 단위를 붙여 적은 값 → 원 단위. **이걸 안 펴면 오탐이 난다**
#  (실측 2026-08-25: 회식 별표4 원문이 "5만원"이라 payload의 50000이 「원문에 없는 숫자」로
#  걸렸다 — 검사가 맞는 값을 틀렸다고 하면 사람이 검사를 안 믿게 된다).
_UNIT = re.compile(r"(\d[\d,]*)\s*(만|천)")


def _numbers(text: str) -> set[int]:
    """본문에 실제로 등장한 정수들. 쉼표를 떼고 만·천 단위를 원으로 편다."""
    text = text or ""
    out = {int(m.replace(",", "")) for m in re.findall(r"\d[\d,]*", text)}
    for digits, unit in _UNIT.findall(text):
        out.add(int(digits.replace(",", "")) * (10_000 if unit == "만" else 1_000))
    return out


def _leaves(node: Any, depth: int) -> tuple[list[Any], bool]:
    """축을 `depth`번 따라간 자리의 값들과 **깊이가 맞았는지**.

    core `context_builder._payload_leaves`와 같은 규칙이다. 여기서 미리 잡는 이유는,
    깊이가 어긋난 표는 승인돼도 `lookup`이 늘 `None`을 주는데 **에러가 안 나기** 때문이다.
    """
    if depth <= 0:
        return [node], not isinstance(node, dict)
    if not isinstance(node, dict):
        return [], False
    out: list[Any] = []
    ok = True
    for v in node.values():
        got, fine = _leaves(v, depth - 1)
        out += got
        ok = ok and fine
    return out, ok and bool(out)


def _keys_at(node: Any, depth: int) -> list[str]:
    """축을 `depth`번 따라간 자리의 **키들**. 값 어휘 대조에 쓴다."""
    if not isinstance(node, dict):
        return []
    if depth <= 0:
        return list(node.keys())
    out: list[str] = []
    for v in node.values():
        out += _keys_at(v, depth - 1)
    return out


def _check(data: dict[str, Any], payload: Any, axes: list[str], dropped: list[str],
           raw: str, vocab: dict[str, list[str]] | None = None) -> list[str]:
    """추출 결과 자동 검사. **고칠 수 있도록 문제를 문장으로** 돌려준다(재시도 입력).

    core `table_proposals.validate`가 승인 시점에 하는 검사를 **추출 시점으로 당긴 것**이다.
    승인 화면에서 막히면 사람이 손으로 고쳐야 하지만, 여기서 걸리면 모델이 다시 만든다.
    """
    problems: list[str] = []

    key = str(data.get("key") or "").strip()
    if not KEY_RE.match(key):
        problems.append(
            f"key `{key}`가 표기 규칙에 어긋납니다 — 영문 소문자·숫자·밑줄 3자 이상,"
            " `_table`로 끝내세요."
        )
    if dropped:
        problems.append(
            "판정 사실에 없는 축을 썼습니다: " + ", ".join(dropped)
            + " — [사용 가능한 축] 목록에서 고르거나, 맞는 축이 없으면 key_axes를 비우고"
              " notes에 그 사실을 적으세요."
        )
    if not isinstance(payload, dict) or not payload:
        problems.append("payload가 비어 있거나 객체가 아닙니다.")
        return problems

    #  **축이 실재하기만 해서는 부족하다.** 실측 2026-08-25: 업무추진비 별표1이
    #  `category.value` 축으로 「검사 통과」였는데 키는 음식물·선물·경조사비였다
    #  (맞는 축은 `category.item_type`). 경로만 보면 못 잡고 값 어휘를 대조해야 잡힌다.
    for depth, axis in enumerate(axes):
        allowed_values = (vocab or {}).get(axis)
        if not allowed_values:
            continue
        unknown = [k for k in _keys_at(payload, depth) if k != "*" and k not in allowed_values]
        if unknown:
            problems.append(
                f"`{axis}` 축의 값이 아닌 항목이 있습니다: " + ", ".join(unknown[:6])
                + f" — 이 축이 가질 수 있는 값은 {', '.join(allowed_values)} 뿐입니다."
                  " 표 내용에 맞는 다른 축을 고르거나, 맞는 축이 없으면 key_axes를 비우세요."
            )

    #  **core `_exposes_scalar`와 같은 규칙이어야 한다.** 축이 없는 표는 중첩이 아니라
    #  `{"value": 스칼라}`다(`lookup`이 마지막에 `node.get("value")`로 꺼낸다). 이걸
    #  깊이 0의 중첩으로 보면 멀쩡한 표가 매번 「깊이 불일치」로 걸린다.
    if not axes:
        if "value" not in payload:
            problems.append('축이 없는 표는 payload가 {"value": 숫자} 형태여야 합니다.')
            leaves, depth_ok = [], True
        else:
            leaves, depth_ok = [payload["value"]], True
    else:
        leaves, depth_ok = _leaves(payload, len(axes))
    if not depth_ok:
        problems.append(
            f"payload 중첩 깊이가 key_axes 길이({len(axes)})와 맞지 않습니다 — 축 하나당"
            " 한 겹씩만 중첩하고 마지막 자리에는 숫자를 두세요."
        )
    if any(isinstance(v, dict) for v in leaves):
        problems.append(
            "값 자리에 객체가 남아 있습니다 — 값 열이 여러 개면 하나만 고르고 나머지는"
            " notes에 적으세요."
        )

    #  **원문에 근거 없는 항목 탐지.** 실측 2026-08-25: 「키를 값 목록의 표기로 쓰라」를
    #  모델이 **어휘 전체를 채우라**로 읽어 `{"회식":50000,"회의":50000,…}`를 냈고 다른
    #  검사를 전부 통과했다 — 조용히 틀렸는데 ✅로 보이는, 이 검사들이 막으려던 상태다.
    #
    #  「모든 값이 같으면 축이 아니다」로는 못 잡는다 — 실제 별표도 세 항목이 다 5만원이다.
    #  구분되는 것은 **키가 표에서 나왔는가**다. 다만 표기 변환(음식물→식사)은 정당하므로
    #  전부가 아니라 **과반이 근거 없을 때만** 잡는다.
    if axes:
        keys = [k for k in _keys_at(payload, 0) if k != "*"]
        anchorless = [k for k in keys if k not in raw]
        if keys and len(anchorless) * 2 > len(keys):
            problems.append(
                "표에서 찾을 수 없는 항목이 대부분입니다: " + ", ".join(anchorless[:6])
                + " — 축의 값 목록은 **표기를 맞추는 용도**이지 채워 넣을 목록이 아닙니다."
                  " 표에 실제로 나온 행만 담으세요."
            )

    #  **지어낸 숫자 탐지.** 원문에 없는 값이 payload에 있으면 셀을 잘못 읽었거나 만든 것이다.
    src = _numbers(raw)
    invented = [
        v for v in leaves
        if isinstance(v, (int, float)) and not isinstance(v, bool) and int(v) not in src
    ]
    if invented:
        problems.append(
            "표 원문에 없는 숫자가 있습니다: " + ", ".join(str(v) for v in invented[:5])
            + " — 원문 셀의 값을 그대로 옮기세요(쉼표·'원'만 제거)."
        )
    return problems


def _usage_note(key: str, axes: list[str], strict: bool) -> str:
    """**이 값이 어디에 어떻게 쓰이는지** 한국어로. 승인 화면이 그대로 보여준다.

    승인하는 사람이 판단할 것은 "이 숫자가 맞나"만이 아니라 "이게 어디에 쓰이나"다.
    화면은 key·축·payload만 보여줬는데 그건 개발자 어휘라, 회계 담당자는 자기가 무엇을
    승인하는지 알 수 없었다.
    """
    field = key[:-6] if key.endswith("_table") else key
    if not axes:
        pick = "표에 값이 하나뿐이라 모든 정산 건에 같은 값이 쓰입니다."
    else:
        pick = "정산 건의 " + " · ".join(f"`{a}`" for a in axes) + " 값으로 행을 골라 씁니다."
    tail = (
        " 축 값을 모르면 이 표는 적용하지 않습니다(모르는 것을 안전하다고 단정하지 않습니다)."
        if strict else " 축 값을 모르면 `*` 기본값이 쓰입니다."
    )
    return f"승인하면 판정 사실 `policy.{field}`가 되어 룰이 이 값과 비교합니다. {pick}{tail}"


def extract_tables(
    table_chunks: list[Any], axis_options: list[dict[str, Any]],
    all_chunks: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """별표·표 청크 → `PolicyTable` 후보 목록.

    축 목록을 프롬프트에 싣는다 — 모델이 축을 지어내면 그 표는 승인 검사에서 막히고
    사람이 다시 고르게 되는데, 애초에 고를 수 있는 것을 보여주면 그 왕복이 없다.

    **임계값 표가 아니라고 판단한 것도 돌려준다**(`skipped=True`). 조용히 버리면 화면에
    아무것도 안 남아, 담당자는 "표가 있는데 왜 후보가 없지"를 스스로 알아내야 한다.
    """
    if not table_chunks:
        return []

    by_id = {c.chunk_id: c for c in (all_chunks or table_chunks)}
    #  어휘가 있는 축은 **고를 수 있는 값까지** 보여준다. 안 보여주고 "목록에서 고르라"고만
    #  하면 모델은 표 머리글을 그대로 쓰고, 그 표기는 판정에서 영영 안 맞는다.
    axes_block = "\n".join(
        f"  {a['path']} ({a['type']}) — {a['desc']}"
        + (f"\n      값: {' | '.join(a['values'])}" if a.get("values") else "")
        for a in axis_options
    )
    allowed = {a["path"] for a in axis_options}
    vocab = {a["path"]: a["values"] for a in axis_options if a.get("values")}
    out: list[dict[str, Any]] = []

    for group in _groups(table_chunks):
        pieces = []
        for i, c in enumerate(group, 1):
            tag = f" (조각 {i}/{len(group)})" if len(group) > 1 else ""
            pieces.append(f"[표 원문{tag} — p{c.page_start}]\n{(c.text or '').strip()}")
        raw = "\n\n".join(pieces)[:TABLE_TEXT_LIMIT]
        if not raw.strip():
            continue

        head = group[0]
        label = (head.article_label or head.citation or head.chunk_id).strip()
        base = f"[사용 가능한 축]\n{axes_block}\n\n{_context_block(group, by_id)}\n\n{raw}"

        data: dict[str, Any] = {}
        payload: Any = {}
        axes: list[str] = []
        dropped: list[str] = []
        problems: list[str] = []
        for attempt in range(TABLE_ATTEMPTS):
            user = base if attempt == 0 else (
                base + "\n\n[직전 출력의 문제 — 고쳐서 다시 만드세요]\n"
                + "\n".join(f"- {p}" for p in problems)
            )
            try:
                got = _chat(_TABLE_SYSTEM, user, _TABLE_SCHEMA, "policy_table_extract",
                            shots=_SHOTS)
            except Exception as exc:  # noqa: BLE001
                logger.warning("별표 추출 실패 chunk=%s: %s", head.chunk_id, exc)
                #  **재시도가 실패해도 첫 결과를 버리지 않는다.** 검사에 걸린 표는
                #  문제를 달아 승인 대기에 올리면 사람이 고칠 수 있지만, 통째로 사라지면
                #  담당자는 그 별표가 있었다는 것조차 모른다.
                if attempt == 0:
                    data = {}
                break
            data = got
            if not data.get("is_threshold_table"):
                break
            try:
                payload = json.loads(data.get("payload_json") or "{}")
            except ValueError:
                payload = {}
            axes = [a for a in (data.get("key_axes") or []) if a in allowed]
            dropped = [a for a in (data.get("key_axes") or []) if a not in allowed]
            problems = _check(data, payload, axes, dropped, raw, vocab)
            if not problems:
                break

        if not data:
            continue

        base_row = {
            "chunkId": ",".join(c.chunk_id for c in group)[:64],
            "label": label[:100],
            "citation": head.citation,
            "pageStart": head.page_start,
            "pageEnd": group[-1].page_end,
            "rawMarkdown": raw,
            "confidence": float(data.get("confidence") or 0.0),
            "comment": str(data.get("comment") or "")[:1000],
        }

        if not data.get("is_threshold_table"):
            #  **버리지 않고 남긴다** — 왜 안 만들었는지가 화면에 보여야 한다.
            out.append({
                **base_row, "skipped": True,
                "skipReason": str(data.get("skip_reason")
                                  or "임계값 표가 아니라고 판단했습니다.")[:500],
                "key": "", "title": "", "keyAxes": [], "payload": {}, "strictKeys": False,
                "notes": "", "checks": [], "usageNote": "",
            })
            continue

        if not isinstance(payload, dict) or not payload:
            continue

        notes = str(data.get("notes") or "")
        if dropped:
            notes = (notes + "\n" if notes else "") + (
                "판정 사실에 없는 축이라 제외했습니다: " + ", ".join(dropped)
                + " — 축을 다시 고르거나, 표에 값이 하나뿐이면 축 없이 두세요."
            )
        #  재시도로도 안 풀린 문제는 **숨기지 않는다.** 승인 화면이 그대로 띄운다.
        checks = [{"level": "warn", "message": m} for m in problems]
        if len(group) > 1:
            checks.append({
                "level": "info",
                "message": f"페이지에 걸쳐 나뉜 표 {len(group)}조각을 하나로 합쳐 읽었습니다.",
            })
        if not problems:
            checks.append({"level": "ok", "message": "축·중첩 깊이·값 검사를 통과했습니다."})

        key = str(data.get("key") or "").strip()[:64]
        strict = bool(data.get("strict_keys"))
        out.append({
            **base_row, "skipped": False, "skipReason": "",
            "key": key,
            "title": str(data.get("title") or "").strip()[:200],
            "keyAxes": axes,
            "payload": payload,
            "strictKeys": strict,
            "notes": notes[:2000],
            "usageNote": _usage_note(key, axes, strict),
            "checks": checks,
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
        result.tables = extract_tables(table_chunks, axis_options or [], chunks)
        result.table_count = len(result.tables)
    except Exception as exc:  # noqa: BLE001
        logger.exception("별표 추출 단계 실패")
        result.error = (result.error + " / " if result.error else "") + (
            f"별표 추출 실패: {type(exc).__name__}: {exc}"
        )
    return result
