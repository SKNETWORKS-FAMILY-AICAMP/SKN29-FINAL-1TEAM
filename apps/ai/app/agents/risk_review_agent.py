"""③ Risk Review Agent — MVP 2단계 (요구사항 §5.5 / 기술명세서 §4.3).

  [1차] 단순 이상거래 탐지(비지도) → anomaly_score + feature_contribs + risk_tier(3단계)
  [2차] RAG 내규 기반 검증 — ①분류(위반 여부) → ②보고서(권장 처리 포함) 2단, MCP 툴콜링(§1)

※ 지도학습(review_probability)·자동 재학습 피드백 루프는 post-MVP 확장.
  회계 결정(decision_labels)은 MVP에선 '적재만'.
  FastAPI는 확정 데이터를 소유하지 않는다 — 이 모듈은 응답만 만들고, 저장은 Django(judge 액션)가 한다.

v1 변경(agent-v1-upgrade-plan.md §2.2, 2026-08-19):
  1. **MCP 툴콜링 전환** — search_policy/search_cases를 파이썬이 미리 실행해 프롬프트에
     박아넣던 방식을 걷어내고, Rule Agent(§1 항목1)와 같은 `mcp_client.call_tool()`
     기반 멀티턴 루프로 바꿨다. LLM이 근거가 부족하다고 판단하면 스스로 재검색한다.
  2. **anomaly_score 3단계 분류(risk_tier)** — 팀 결정(2026-08-19): 재학습돼도 안 흔들리는
     고정 스코어 임계값. 현재 배포된 `anomaly.pkl`의 실측 calibration_table(10분위)에서
     "80~90% 밴드(관측 이상비율 1.7%) → 90~100% 밴드(관측 이상비율 28.19%, 기준 대비
     lift 8.08배)"로 관측 비율이 급등하는 지점을 근거로 HIGH 경계를 잡았고, 기존 운영
     `is_outlier` 컷오프(모델의 `threshold`, train 90번째 백분위수 근사)를 MEDIUM 경계로
     그대로 썼다. 모델을 재학습해도 이 두 상수는 코드에서 다시 계산하지 않는다(그게
     "고정 임계값"을 고른 이유) — 분포가 크게 달라지면 재학습 시 사람이 다시 실측해
     상수를 갱신해야 한다.
  3. **분류(violation_verdict) ↔ 권장 처리(recommendation) 분리** — 위반 여부는 ①분류가
     정하고, 권장 처리는 그 결과가 **허용하는 값 안에서만** 나온다(`_ALLOWED_RECOMMENDATION`).
     판단(사실관계)과 처리방침(정책적 선택)을 섞지 않되, **처리방침이 판단을 뒤집지도
     못하게** 한다. **반환 계약(dict shape)은 그대로 유지**(§3 비침습 체크리스트).

v2 정정(2026-08-28, 검증 100건 실측 → `docs/report/risk-review-agent-report.md`):
  · 권장 처리 규칙을 가진 액션 전용 호출(`_decide_action`)이 **어디서도 불리지 않았고**
    보고서 프롬프트엔 그 규칙이 없어, 「위반 아님」 72건 중 52건에 보완요청이 붙었다.
    회귀 테스트가 그 죽은 함수를 직접 import해 검증하고 있어 오래 안 드러났다.
  · 고친 방향: **LLM 호출을 늘리지 않는다.** 규칙 표 하나(`_ALLOWED_RECOMMENDATION`)를
    ①출력 스키마 ②프롬프트 ③서버 정정 **세 곳이 같이** 보게 하고, 죽은 호출은 지웠다.
    같은 값을 주는 창구가 둘이면 하나는 반드시 뒤처진다.
  · 보고서에 **검증 → 재작성 루프**를 넣었다(`_report_problems`, 최대 2회).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Literal

from openai import OpenAI
from pydantic import BaseModel

from app.agents import mcp_client
from app.clients import core_client
from app.config import settings
from app.mcp import tools
from app.ml.registry import get_active_model
from app import llm
from app.agents.review_notables import notables
from app.rag.retrieval import build_query, facts_nl

# 4629076 이후 main에서 병합된 리트리벌 품질 개선(2026-08-19, c605e99/21ffe4f)을 이 v1
# 재작성 위에 그대로 접목한다 — ① build_query(자연어 질의+facts_nl, 원시 피처명 노출 금지,
# ΔMRR +0.020 실측) ② _format_policy_chunks의 parent_text(같은 조 전문) 포함 ③ 분류
# 프롬프트의 "확정 판정엔 유보 표현 금지" 규칙.

logger = logging.getLogger(__name__)

MODEL = "gpt-4o-mini"

# ── risk_tier 임계값 — **분포가 갈리는 지점**으로 잡는다 (2026-08-26) ──────────────
#
# ## 등급의 뜻 — 비율 목표가 아니다
#
#   · LOW    LLM을 **한 번도 안 부른다.** 그래서 「거의 정상이라고 확신할 수 있는」
#            구간이어야 한다 — 확신 없이 넘기면 그대로 놓친다.
#   · HIGH   heavy 모델로 2차 RAG 내규 검증까지 간다. 비싸므로 「위험한 건이 확실히
#            많은」 구간이어야 값어치가 있다.
#   · MEDIUM 그 사이의 **애매한 전부.** 확신이 어느 쪽으로도 안 서는 구간이라
#            **비대해지는 것이 정상이다** — fast 모델로 한 번은 보고 넘어간다.
#
# 룰엔진이 「확실한 것만 확정하고 나머지는 검토로」 하는 것과 같은 구조다
# ([[rule-engine-semantics]]). 양 끝을 좁게 잡고 가운데를 넓게 둔다.
#
# ⛔ **10/20/70 같은 비율 목표로 잡으면 안 된다.** 그러면 LOW가 비대해지고, 확신 없는
#    건을 LLM 0회로 흘려보내게 된다.
#
# ## 지금 값의 근거 — 약한 경향뿐이다
#
# `seed_adopted` 185건 실측. 위험 프록시(RETURN/REJECT/REVIEW)의 점수 10분위 분포:
#
#     d1  -0.0087~0.0025   위험 0%     ┐ 이 아래는 한 건도 없다 → LOW
#     d2   0.0026~0.0105   위험 0%     ┘
#     d3~d9 0.0109~0.0713  위험 0~6%   ← 경향이 없다 → MEDIUM
#     d10  0.0718~0.1128   위험 11%    ← 여기서 두 배 이상 → HIGH
#
# ⚠️ **위험 라벨이 5건(2.7%)뿐이라 이건 분리점이 아니라 힌트다.** d10의 11%도 19건 중
# 2건이라 노이즈와 구분되지 않는다. 그래도 「하위 20%에 위험이 0건」과 「상위 10%에
# 밀도가 가장 높다」는 방향은 일관되므로 그 경계를 쓴다.
#
# 이 값을 제대로 정하려면 무엇이 필요한지는 [[risk-review-agent-v2]] §컷오프 결정 계획.
RISK_TIER_HIGH_THRESHOLD = 0.072    # p90 — 위험 밀도가 꺾이는 지점(d10 진입)
RISK_TIER_MEDIUM_THRESHOLD = 0.011  # p20 — 이 아래는 위험 관측 0건

MAX_TOOL_TURNS = 6  # §1 항목1과 동일한 안전판 근거(search 2~3회 + 최종 제출 여유)

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


#: 등급 강제 스위치 — **임시**다. 컷오프 근거가 위험 라벨 5건뿐이라 표본이 바뀌면
#  전건이 한쪽으로 쏠린다(검증셋 100건 실측: 96건이 LOW로 떨어져 2차 검증을 한 번도
#  못 받았다 → `docs/report/risk-review-agent-report.md` §5-①). 컷오프를 다시 산출할
#  때까지 **모든 건을 MEDIUM으로 고정해** 2차 검증을 태우려고 둔 문이다.
#
#  `DOCLING_MOCK`과 같은 규율을 따른다 — ① 호출 시점에 env를 읽어 `docker exec -e`로
#  프로세스 단위 지정이 되고 ② 켜져 있으면 **WARNING 로그와 결과의 `note`에 그대로
#  드러낸다.** 진짜 위험은 켠 걸 잊는 것이라, 조용히 동작하면 안 된다.
_TIER_OVERRIDE_VALUES = ("LOW", "MEDIUM", "HIGH")


def _tier_override() -> str:
    raw = os.getenv("RISK_TIER_OVERRIDE") or getattr(settings, "risk_tier_override", "") or ""
    value = raw.strip().upper()
    return value if value in _TIER_OVERRIDE_VALUES else ""


def _risk_tier(anomaly_score: float) -> Literal["HIGH", "MEDIUM", "LOW"]:
    forced = _tier_override()
    if forced:
        logger.warning("risk_tier 강제 고정: %s (RISK_TIER_OVERRIDE) — 점수 %.4f는 무시된다",
                       forced, anomaly_score)
        return forced  # type: ignore[return-value]
    if anomaly_score >= RISK_TIER_HIGH_THRESHOLD:
        return "HIGH"
    if anomaly_score >= RISK_TIER_MEDIUM_THRESHOLD:
        return "MEDIUM"
    return "LOW"


# ── LLM 구조화 출력 스키마(Structured Output) ─────────────────────────────

class Citation(BaseModel):
    doc: str
    article: str
    quote_summary: str


class SimilarCase(BaseModel):
    case_id: str
    outcome: str
    relevance: str


class Classification(BaseModel):
    """①분류 단계 산출물 — 위반 여부·근거만. 처리방침(recommendation)은 포함하지 않는다."""
    violation_verdict: Literal["VIOLATION", "NO_VIOLATION", "INSUFFICIENT_INFO"]
    review_reasons: list[str]
    citations: list[Citation]
    similar_cases: list[SimilarCase]


# ── ②보고서: 담당자가 읽는 산출물 ──────────────────────────────────────
#
#  **마크다운 한 덩어리로 받지 않는다.** 화면이 미리보기(요약)와 자세히(특징·근거·안내)를
#  갈라야 하는데 텍스트 블록이면 못 자른다. 그리고 근거는 이미 `citations`로 구조화돼
#  있어서, 본문에 또 쓰면 같은 사실이 두 곳에서 관리된다.

class ReportEvidence(BaseModel):
    """판단을 뒷받침하는 근거 하나. `ref`는 **실제 검색 결과의 id**여야 한다."""
    kind: Literal["policy", "case"]
    ref: str          # chunk_id 또는 case_id — 서버가 검색 결과와 대조해 검증한다
    label: str        # "법인카드 사용규정 제11조②" 처럼 사람이 읽는 출처
    quote: str        # 실제 발췌. 지어낸 인용을 막기 위해 반드시 원문에서 가져온다


class ReportFinding(BaseModel):
    """근거와 판단을 **한 덩어리로** 묶는다.

    지금까지 `citations`(근거)와 `review_reasons`(사유)가 별개 배열이라, 어느 조항이 어느
    판단을 뒷받침하는지 담당자가 되짚을 수 없었다.
    """
    claim: str            # 무엇이 문제인가 / 문제없다고 본 근거는 무엇인가
    reasoning: str        # 왜 그렇게 판단했나(사실 → 규정 적용)
    evidence: list[ReportEvidence]


class RiskReport(BaseModel):
    """검토 화면이 그대로 그리는 보고서."""
    summary: str                                          # 미리보기 — 2문장 이내
    recommendation: Literal["APPROVE", "SUPPLEMENT", "REJECT"]
    highlights: list[str]                                 # ① 눈여겨볼 특징(거래 사실에서만)
    findings: list[ReportFinding]                         # ② 근거 + 판단 이유
    advisories: list[str]                                 # ③ 담당자가 추가로 고려할 것


#: 분류 결과가 허용하는 권장 처리. **`_ACTION_FALLBACK`과 같은 규칙**이고, 이 표가
#  프롬프트·출력 스키마·서버 검증 세 곳의 단일 출처다.
#
#  이 표가 없던 동안 무슨 일이 있었나(검증 100건 실측): 규칙을 가진 `_decide_action`이
#  **호출되지 않았고** 보고서 프롬프트엔 그 규칙이 없어서, 「위반 아님」 72건 중 52건에
#  보완요청이 붙었다. 모델이 지시를 어긴 게 아니라 **지시가 전달되지 않았다.**
#  → `docs/report/risk-review-agent-report.md` §5-②
_ALLOWED_RECOMMENDATION: dict[str, tuple[str, ...]] = {
    "NO_VIOLATION": ("APPROVE",),
    "VIOLATION": ("REJECT", "SUPPLEMENT"),
    "INSUFFICIENT_INFO": ("SUPPLEMENT",),
}


class _ReportApprove(RiskReport):
    """위반 아님 — 승인 외에는 **낼 수 없다.**"""
    recommendation: Literal["APPROVE"]


class _ReportViolation(RiskReport):
    """위반 — 수위(반려/보완)는 모델이 고른다. 그건 정말로 판단의 영역이다."""
    recommendation: Literal["REJECT", "SUPPLEMENT"]


class _ReportHold(RiskReport):
    """판단 보류 — 근거가 부족한 것이지 문제가 없는 것이 아니다."""
    recommendation: Literal["SUPPLEMENT"]


#: 분류 결과별 출력 스키마. **낼 수 없어야 하는 값은 지시가 아니라 스키마에서 뺀다** —
#  Rule Agent가 자동 통과를 스키마에서 뺀 것과 같은 장치다.
_REPORT_MODEL: dict[str, type[RiskReport]] = {
    "NO_VIOLATION": _ReportApprove,
    "VIOLATION": _ReportViolation,
    "INSUFFICIENT_INFO": _ReportHold,
}


# ── ①분류: MCP 툴콜링 프롬프트 ─────────────────────────────────────────

_CLASSIFY_SYSTEM_PROMPT = """당신은 법인카드 정산 Risk Review의 2차(내규 검증) 담당입니다.
1차 비지도 이상탐지가 이상 후보로 올린 건에 대해, 아래에 주어지는 근거(규정 조항 발췌·유사
과거 사례) 및 필요시 `search_policy`/`search_cases` 툴로 직접 검색한 추가 근거를 사용해
내규 위반 여부를 판단하세요. 여기서는 "위반인가 아닌가"만 판단합니다 — 승인/반려 등
처리방침은 다음 단계에서 별도로 결정되므로 여기서 정하지 않습니다.

반드시 지켜야 할 규칙:
1. 주어진 1차 검색 결과만으로 부족하다고 판단되면 `search_policy`/`search_cases`를 다른
   질의로 호출해 추가 근거를 확보하세요(예: 카테고리+가맹점 키워드, 튀는 피처 키워드 등).
2. 출처 표기는 반드시 「문서명」제N조(조항 제목) 전체 형식으로만 인용하세요. "제11조"처럼
   조 번호만 쓰거나 문서명을 생략하는 축약 인용은 금지합니다. 검색된 청크의 citation
   문자열을 그대로 doc/article에 나눠 담고, quote_summary는 해당 조항 내용을 1문장으로
   요약하세요.
3. 검색으로 찾지 못한 규정·조항·수치를 스스로 만들어내지 마세요. 근거가 없으면 citations를
   빈 배열로 두세요. similar_cases의 case_id도 마찬가지입니다 — 검색 결과에 표시된
   `case_id=...` 값을 **그대로 복사**하세요. citation 문자열(예: "과거 반려사례 #0511")의
   일부를 case_id로 쓰지 마세요. 그건 사례 번호가 아니라 사람이 읽는 라벨입니다.
4. 근거로 위반/비위반을 판단할 수 없으면 violation_verdict를 절대 VIOLATION이나
   NO_VIOLATION으로 억지로 결론짓지 말고 INSUFFICIENT_INFO를 반환하세요.
   - "정보가 없어서 검토 필요"(근거 자체가 검색되지 않음)와 "판단이 애매해서 검토 필요"
     (근거는 있으나 이 사안에 명확히 적용되지 않음)는 서로 다른 상황입니다. review_reasons에
     이 둘을 구분해서 서술하세요(예: "정보 없음: policy_docs에서 해당 지출 유형 관련 조항이
     검색되지 않았습니다" vs "판단 보류: 제12조가 있으나 이 건의 구체 상황(공용카드 실사용자
     미기재)까지는 다루지 않습니다").
   - 반대로 violation_verdict가 VIOLATION 또는 NO_VIOLATION이면 이미 결론을 낸 것이므로
     review_reasons도 확정적으로 서술하세요. "판단 보류"·"검토 필요"·"~일 가능성이 높습니다"
     같은 유보 표현은 INSUFFICIENT_INFO 전용입니다 — 결론과 서술이 어긋나면 사람이 읽었을 때
     실제로 확정된 건지 다시 봐야 하는 건지 헷갈립니다.
5. 세법(tax_refs) 판단은 요구하지 않습니다 — policy_docs(사내 규정)와 case_history
   (과거 유사 사례)만 근거로 사용하고, 세무상 손금 처리 여부 등은 판단하지 마세요.
6. 준비되면 반드시 `submit_classification` 툴을 호출해 최종 분류 결과를 제출하세요 —
   이 툴을 호출해야 이 단계가 끝납니다."""

_CLASSIFY_USER_PROMPT_TEMPLATE = """[1차 이상탐지 결과]
anomaly_score: {anomaly_score:.3f} (risk_tier: {risk_tier})
튀는 피처(근사 기여도): {contribs}

[검토 대상 거래 — 담당자 화면에 이미 보이는 것]
가맹점: {merchant}
금액: {amount}원
분류: {category}
지출 목적: {purpose}
거래 사실: {facts}

`search_policy`/`search_cases`로 근거를 찾은 뒤 `submit_classification`을 호출하세요."""

_SEARCH_POLICY_TOOL = {
    "type": "function",
    "function": {
        "name": "search_policy",
        "description": "사내 규정 조항을 RAG로 검색한다(MCP search_policy 경유).",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "description": "검색 질의"},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query", "top_k"],
        },
    },
}

_SEARCH_CASES_TOOL = {
    "type": "function",
    "function": {
        "name": "search_cases",
        "description": "과거 유사 승인/반려/보완요청 사례를 RAG로 검색한다(MCP search_cases 경유).",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "description": "검색 질의"},
            },
            "required": ["query"],
        },
    },
}


def _format_policy_chunks(chunks: list[dict]) -> str:
    """policy_docs 검색 결과를 LLM 프롬프트용 텍스트로 조립.

    [수정 2026-08-19] `store.search()`가 잎 청크의 부모(조문 전체)를 이미 가져오고 있었는데,
    여기서는 잎 청크 원문(`text`)을 400자로 자른 것만 써서 애써 가져온 문맥이 프롬프트 직전에
    버려지고 있었다 — 긴 조는 항 단위로 쪼개져 검색되므로 잎 하나만 보이면 같은 조의 다른 항이
    통째로 안 보인다. 이제 부모(조 전문)를 **덧붙인다**(잎을 대체하지 않는다):
    검색이 실제로 걸린 잎을 앞에 두고 조 전문을 맥락으로 잇는 편이, 조 전문만 넘겨 어느 항이
    걸린 건지 지워버리는 것보다 근거가 뾰족하다. 부모가 없거나(atomic 청크) 잎과 같으면 잎만 쓴다.
    """
    if not chunks:
        return "(검색 결과 없음)"
    lines = []
    for c in chunks:
        line = f"- {c['citation']}: {c['text'][:400]}"
        # 인용은 잎의 citation을 그대로 쓴다 — 부모를 인용하면 "제N조" 통째로가 근거로 찍혀
        # 근거가 뭉툭해진다. rule_agent_v0/agent.py::_format_chunks와 동일 계약.
        if c.get("parent_text") and c["parent_text"] != c["text"]:
            line += f"\n  (같은 조 전문 — 맥락 참고용, 인용은 위 citation을 쓸 것): {c['parent_text'][:800]}"
        lines.append(line)
    return "\n".join(lines)


def _format_case_hits(cases: list[dict]) -> str:
    """`case_id`를 **반드시 함께 노출**한다 — 스키마(`submit_classification.similar_cases`)가
    case_id를 요구하는데 여기서 안 보여주면 모델은 알 길이 없어 citation 조각을 지어낸다.

    실측(2026-08-19): case_id를 뺀 채로 돌렸더니 실제 id가 `case-golden-005`인 사례를 모델이
    `#0511`(citation 문자열의 일부)로 채웠다. 그 값이 Django `rag_refs`의 "사례 …"에 그대로
    실려 검토 화면에 뜨는데, 우리 `case_history`엔 없는 id라 원 사례로 되짚을 수 없었다.
    """
    if not cases:
        return "(검색 결과 없음)"
    return "\n".join(
        f"- case_id={c['case_id']} [{c['outcome']}] {c['citation']}: {c['text'][:300]}"
        for c in cases
    )


_SUBMIT_CLASSIFICATION_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_classification",
        "description": "최종 분류 결과(위반 여부·근거)를 제출한다. 이 툴을 호출해야 분류 단계가 끝난다.",
        "strict": True,
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "violation_verdict": {
                    "type": "string",
                    "enum": ["VIOLATION", "NO_VIOLATION", "INSUFFICIENT_INFO"],
                },
                "review_reasons": {"type": "array", "items": {"type": "string"}},
                "citations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "doc": {"type": "string"},
                            "article": {"type": "string"},
                            "quote_summary": {"type": "string"},
                        },
                        "required": ["doc", "article", "quote_summary"],
                    },
                },
                "similar_cases": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "case_id": {"type": "string"},
                            "outcome": {"type": "string"},
                            "relevance": {"type": "string"},
                        },
                        "required": ["case_id", "outcome", "relevance"],
                    },
                },
            },
            "required": ["violation_verdict", "review_reasons", "citations", "similar_cases"],
        },
    },
}


def _insufficient_info_fallback(reason: str) -> dict:
    return {
        "violation_verdict": "INSUFFICIENT_INFO",
        "review_reasons": [reason],
        "citations": [],
        "similar_cases": [],
    }


def _safe_search(tool_name: str, result_key: str, **kwargs: Any) -> list[dict]:
    """MCP 검색 1회. 장애는 빈 결과로 격하하고 사유만 남긴다(호출부가 2차를 계속 태우도록).

    빈 결과와 장애를 구분하는 것 자체는 `mcp/tools.py::search_policy` 계약이 맞다 — 다만 그
    구분은 **로그**로 하고, 판정 흐름은 멈추지 않는다. 여기서 예외를 올리면 Django가 `RiskReview`
    행을 아예 안 만들어 검토자가 근거는커녕 흔적도 못 본다(`_stage1` docstring 참조).
    """
    try:
        return mcp_client.call_tool(tool_name, **kwargs).get(result_key, [])
    except Exception as exc:  # noqa: BLE001  # Chroma 미기동·임베딩 API 오류 등
        logger.warning("%s 실패(%s) — 근거 없이 진행: %s", tool_name, kwargs.get("query"), exc)
        return []


def _build_classify_prompt(
    summary: dict, stage1: dict, initial_query: str, policy_hits: list[dict], case_hits: list[dict]
) -> str:
    """①분류 첫 턴에 심는 시드 프롬프트 — 순수 문자열 조립만(네트워크 없음), 단위 테스트 대상."""
    contribs = stage1.get("contribs", [])
    return (
        _CLASSIFY_USER_PROMPT_TEMPLATE.format(
            anomaly_score=stage1.get("anomaly_score", 0.0),
            risk_tier=stage1.get("risk_tier", "LOW"),
            contribs=", ".join(f"{c['feature']}({c['weight']})" for c in contribs) or "(없음)",
            merchant=summary["merchant"],
            amount=summary["amount"],
            category=summary["category"],
            purpose=summary.get("purpose") or "(미기재)",
            facts=facts_nl(summary) or "(없음)",
        )
        + f"\n\n[근거 — policy_docs 1차 검색 결과(질의: {initial_query!r})]\n{_format_policy_chunks(policy_hits)}"
        + f"\n\n[근거 — case_history 1차 검색 결과]\n{_format_case_hits(case_hits)}"
        + "\n\n위 근거로 충분하면 바로 `submit_classification`을 호출하세요. 부족하면 "
          "`search_policy`/`search_cases`를 다른 질의로 추가 호출한 뒤 제출하세요."
    )


def _classify(summary: dict, stage1: dict, profile: str = "fast") -> dict:
    """①분류: MCP 툴콜링 멀티턴 루프. `submit_classification` 호출 시 그 인자를 결과로 반환.

    Rule Agent(§1 항목1)와 같은 이유로 **초기 검색 1회분을 파이썬이 먼저 실행**해 대화
    맥락에 고정으로 심어둔다 — 그러지 않으면 모델이 매번 첫 턴을 "질의 없이 무작정 검색"에
    쓰게 되고, search_policy·search_cases 두 툴을 오가며 재검색만 반복하다 MAX_TOOL_TURNS를
    다 쓰고도 한 번도 submit하지 못하는 사례가 실측됐다(정상 케이스에서도 발생, 2026-08-19).
    모델은 이 초기 근거로 부족하다고 판단할 때만 추가 검색한다.

    초기 질의는 `app.rag.retrieval.build_query`(자연어 질의+판정필드, main 병합분
    c605e99/21ffe4f)로 조립한다 — 원시 피처명을 그대로 이어붙이던 방식보다 검색 품질이
    유의하게 낫다고 실측된 방식(ΔMRR +0.020)이라 v1의 프리시드에도 그대로 적용한다.
    """
    contribs = stage1.get("contribs", [])
    initial_query = build_query(summary["category"], summary["merchant"], contribs, summary)

    # 프리시드 검색 실패(Chroma 다운 등)로 2차 전체를 죽이지 않는다 — 근거가 비면 모델이
    # 툴로 다시 찾아보거나, 그래도 없으면 INSUFFICIENT_INFO로 정직하게 수렴한다.
    # "검색이 안 됐다"와 "검색했는데 없다"는 다른 상황이라 사유를 프롬프트에 명시한다.
    #
    # rerank=True(main 병합분, 2026-08-19): 벡터 top-k를 그대로 쓰면 화제만 겹치는 조항
    # (예: "위반 시 조치")이 섞여 들어와 결론이 흐려진다 — LLM이 실제로 이 질의에 답하는
    # 것만 추려서 넘긴다. `mcp/tools.py::search_policy` 독스트링: "Risk Review 2차 검증은
    # 항상 켠 채로 부른다" — v1 툴콜링 루프의 모든 search_policy 호출(프리시드+추가검색)에
    # 동일하게 적용한다.
    # scope=이 정산의 category — 검색을 그 카테고리(+공통 규정) 문서로 좁힌다. 안 그러면
    # 화제가 겹치는 다른 카테고리 규정(예: 회식 규정)이 식대·회의 건에 새어 들어온다
    # (QA 2026-08-24 실측 결함, `default-gate.md`류 카논과 같은 성격의 스코프 누수).
    initial_policy = _safe_search(
        "search_policy", "chunks", query=initial_query, top_k=6, rerank=True,
        scope=summary["category"],
    )
    initial_cases = _safe_search("search_cases", "similar_cases", query=initial_query)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _CLASSIFY_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _build_classify_prompt(summary, stage1, initial_query, initial_policy, initial_cases),
        },
    ]

    tool_specs = [_SEARCH_POLICY_TOOL, _SEARCH_CASES_TOOL, _SUBMIT_CLASSIFICATION_TOOL]

    for _ in range(MAX_TOOL_TURNS):
        resp = llm.chat(
            profile,
            messages=messages,
            timeout=60,          # heavy 프로파일은 추론 시간이 붙는다(실측 ~23초/호출)
            temperature=0.2,     # heavy면 어댑터가 떨어뜨린다(커스텀 온도 미지원)
            tools=tool_specs,
            tool_choice="auto",
        )
        msg = resp.choices[0].message
        tool_calls = msg.tool_calls or []

        if not tool_calls:
            messages.append({"role": "assistant", "content": msg.content or ""})
            messages.append({
                "role": "user",
                "content": "반드시 `submit_classification` 툴을 호출해 최종 분류 결과를 제출하세요.",
            })
            continue

        messages.append({
            "role": "assistant", "content": msg.content,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in tool_calls
            ],
        })

        for tc in tool_calls:
            # 툴 인자는 LLM이 만든 문자열이라 JSON이 깨질 수 있다(드물지만 잘림·인용부호 오류).
            # 여기서 그냥 터뜨리면 2차 검증 전체가 유실되므로, 그 툴 호출만 실패로 돌려주고
            # 모델이 다시 시도하게 한다.
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError as exc:
                logger.warning("툴 인자 JSON 파싱 실패(%s): %s", tc.function.name, exc)
                messages.append({
                    "role": "tool", "tool_call_id": tc.id,
                    "content": f"인자 JSON을 파싱하지 못했습니다({exc}). 올바른 JSON으로 다시 호출하세요.",
                })
                continue

            if tc.function.name == "submit_classification":
                try:
                    return Classification.model_validate(args).model_dump()
                except Exception as exc:  # noqa: BLE001 — LLM이 스키마를 어긴 극단적 경우
                    logger.warning("submit_classification 검증 실패: %s", exc)
                    return _insufficient_info_fallback(
                        f"LLM 분류 결과가 스키마를 위반했습니다({type(exc).__name__}) — 사람 검토 필요"
                    )
            if tc.function.name == "search_policy":
                hits = _safe_search(
                    "search_policy", "chunks",
                    query=args.get("query") or initial_query, top_k=args.get("top_k") or 6,
                    rerank=True, scope=summary["category"],
                )
                tool_content = _format_policy_chunks(hits)
            elif tc.function.name == "search_cases":
                hits = _safe_search(
                    "search_cases", "similar_cases", query=args.get("query") or initial_query,
                )
                tool_content = _format_case_hits(hits)
            else:
                tool_content = f"알 수 없는 툴: {tc.function.name}"
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_content})

    return _insufficient_info_fallback(
        f"모델이 {MAX_TOOL_TURNS}턴 안에 submit_classification을 호출하지 않았습니다 — 사람 검토 필요"
    )


# ── ②액션: 분류 결과만 입력받아 권장 처리 결정 ────────────────────────────

_ACTION_FALLBACK = {
    "NO_VIOLATION": "APPROVE",
    "VIOLATION": "SUPPLEMENT",
    "INSUFFICIENT_INFO": "SUPPLEMENT",
}


_REPORT_SYSTEM_PROMPT = """당신은 법인카드 정산 위험 검토 보고서를 쓰는 담당자입니다.
1차 이상탐지와 2차 내규 검증이 이미 끝났고, 그 결과를 **회계 담당자가 읽고 결정할 수 있는
보고서**로 옮기는 것이 당신의 일입니다.

반드시 지켜야 할 규칙:
1. **주어진 사실과 근거 밖의 내용을 쓰지 마세요.** 거래 사실에 없는 참석 인원·거래처명·
   장소를 추측해 넣으면 안 됩니다. 모르면 쓰지 않습니다.
2. **모든 finding에는 근거(evidence)를 답니다.** 근거를 댈 수 없는 지적은 finding이 아니라
   advisories(담당자가 확인해 볼 것)에 넣으세요. 근거 없는 판단은 판단이 아닙니다.
3. **evidence.ref는 주어진 근거 목록의 id를 그대로** 쓰세요. 지어내면 서버가 버립니다.
   evidence.quote는 주어진 발췌에서 가져오고, 없는 문장을 만들지 마세요.
4. **위반이 없다고 판단해도 finding을 하나 씁니다** — 무엇을 대조해 문제없다고 보았는지가
   판단의 내용입니다. 빈 목록은 "검증하지 않았다"로 읽힙니다.
5. highlights는 **담당자가 화면만 봐서는 알 수 없는 것**을 씁니다. 가맹점·금액·결제
   시각·분류는 검토 목록에 이미 떠 있으니 되풀이하지 마세요 — 그건 도움이 아니라 소음입니다.
   눈여겨볼 것은 이런 종류입니다:
   · **과거와의 관계** — 같은 가맹점 반복, 일·월 누적액이 한도에 근접
   · **값의 출처와 신뢰도** — 인원이 본인 신고인지 문서로 확인된 것인지, 업종 판정이 확실한지
   · **어긋난 짝** — 신고 인원과 문서 인원이 다름, 실사용자와 지출자가 다름
   · **판단하지 못한 것** — 무엇을 몰라서 자동 판정이 보류됐는지
   아래 [눈여겨볼 사실] 목록이 그 후보입니다. **그 목록에 있는 것만** 쓰고, 담당자가 바로
   행동할 수 있게 한 줄씩 풀어 쓰세요(숫자는 근거이므로 그대로 옮깁니다).
   목록이 비어 있으면 highlights도 빈 배열로 두세요 — 채우려고 화면에 있는 사실을 옮겨
   적으면 담당자는 다음부터 이 칸을 안 읽습니다.
6. advisories는 **담당자가 추가로 확인·고려할 것**입니다. 시스템이 확인할 수 없어 사람이
   봐야 하는 것(참석자 명단 대조, 사전승인 문서 확인 등)을 씁니다.
   highlights가 「무엇이 보이는가」라면 advisories는 「그래서 무엇을 해봐야 하는가」입니다 —
   같은 내용을 두 칸에 나눠 적지 마세요.
7. summary는 **2문장 이내**입니다. 무엇이 문제이고(또는 문제없고) 무엇을 권하는지.
8. 내부 필드명(evidence.has_valid_receipt 같은 것)·플래그 코드를 본문에 노출하지 마세요.
   담당자가 쓰는 일상어로 씁니다.
9. 판단 보류(INSUFFICIENT_INFO)면 승인(APPROVE)을 권하지 마세요 — 근거가 부족한 것이지
   문제가 없는 것이 아닙니다.
10. **권장 처리(recommendation)는 이미 끝난 위반 여부 분류를 그대로 따릅니다.** 당신이
   위반 여부를 다시 판단하는 자리가 아닙니다:
   · 위반 아님(NO_VIOLATION)  → APPROVE. **「확인해 보면 좋겠다」는 보완요청 사유가
     아닙니다.** 더 볼 것이 있으면 advisories에 쓰세요 — 그러라고 있는 칸입니다.
   · 위반(VIOLATION)          → REJECT 또는 SUPPLEMENT. 시정이 불가능하면 REJECT,
     소명·보완으로 해소되면 SUPPLEMENT.
   · 판단 보류(INSUFFICIENT_INFO) → SUPPLEMENT."""

_REPORT_USER_PROMPT_TEMPLATE = """[2차 내규 검증 결과]
위반 판정: {violation_verdict}
검토 사유: {review_reasons}

[1차 이상탐지]
anomaly_score: {anomaly_score} (등급 {risk_tier}) {anomaly_note}

[검토 대상 거래]
가맹점: {merchant}
금액: {amount}원
분류: {category}
지출 목적: {purpose}
거래 사실: {facts}

[눈여겨볼 사실 — 화면에 없는 것. highlights는 여기서만 고릅니다]
{notables}

[사용 가능한 근거 — evidence.ref는 여기 있는 id만 쓰세요]
{evidence_pool}

[권장 처리 — 위 분류가 허용하는 값은 이것뿐입니다]
{allowed_recommendation}

위 내용으로 보고서를 작성하세요."""


def _evidence_pool(classification: dict) -> tuple[str, dict[str, dict]]:
    """모델에게 보여줄 근거 목록 + 서버가 대조할 색인.

    색인이 있어야 모델이 지어낸 `ref`를 걸러낼 수 있다(Draft Agent가 플래그 코드를
    목록 밖이면 버리는 것과 같은 장치).
    """
    index: dict[str, dict] = {}
    lines: list[str] = []
    for c in classification.get("citations") or []:
        ref = str(c.get("chunk_id") or "").strip()
        label = f"「{c.get('doc', '')}」{c.get('article', '')}".strip()
        if not ref:
            continue
        index[ref] = {"kind": "policy", "label": label, "quote": c.get("quote_summary", "")}
        lines.append(f"- [policy] id={ref} · {label} · {c.get('quote_summary', '')}")
    for sc in classification.get("similar_cases") or []:
        ref = str(sc.get("case_id") or "").strip()
        if not ref:
            continue
        label = f"사례 {ref} ({sc.get('outcome', '')})"
        index[ref] = {"kind": "case", "label": label, "quote": sc.get("relevance", "")}
        lines.append(f"- [case] id={ref} · {label} · {sc.get('relevance', '')}")
    return ("\n".join(lines) or "(없음)", index)


def _validate_report(report: RiskReport, classification: dict, index: dict[str, dict]) -> dict:
    """**모델 출력을 그대로 믿지 않는다.** 서버가 대조·강등한다.

    ① `ref`가 실제 근거 목록에 없으면 그 evidence를 버린다(지어낸 인용).
    ② 근거가 하나도 안 남은 finding은 **advisories로 강등**한다 — "근거는 없지만 확인해
       보세요"는 유효한 안내지만, 판단으로 제시되면 안 된다.
    ③ 판단 보류인데 승인을 권하면 보완요청으로 정정한다(배너와 본문이 다른 말을 하면 안 된다).
    ④ finding이 하나도 없으면 화면에서 「검증 안 함」과 구분되지 않으므로 최소 한 줄을 만든다.
    """
    verdict = classification.get("violation_verdict", "")
    findings: list[dict] = []
    advisories = list(report.advisories)
    dropped_refs: list[str] = []

    for finding in report.findings:
        evidence = []
        for e in finding.evidence:
            known = index.get(e.ref)
            if known is None:
                dropped_refs.append(e.ref)
                continue
            #  라벨·인용은 **서버가 가진 원본**으로 덮는다 — 모델이 옮겨 적다 바꿔도
            #  화면에는 실제 검색 결과가 뜬다.
            evidence.append({"kind": known["kind"], "ref": e.ref,
                             "label": known["label"], "quote": known["quote"] or e.quote})
        if evidence:
            findings.append({"claim": finding.claim, "reasoning": finding.reasoning,
                             "evidence": evidence})
        else:
            advisories.append(f"{finding.claim} (근거 조항을 확인하지 못해 참고 사항으로 남깁니다)")

    if dropped_refs:
        logger.info("보고서에서 알 수 없는 근거 id를 버렸다: %s", sorted(set(dropped_refs)))

    #  분류가 허용하지 않는 권고는 **마지막에 코드가 되돌린다.** 스키마·프롬프트·재시도를
    #  다 통과해도 여기서 한 번 더 막는다 — 셋 다 확률이지만 이건 보장이다.
    recommendation = report.recommendation
    allowed = _ALLOWED_RECOMMENDATION.get(verdict)
    if allowed and recommendation not in allowed:
        corrected = _ACTION_FALLBACK.get(verdict, "SUPPLEMENT")
        logger.warning("권고가 분류와 어긋난다(%s → %s) — %s로 정정한다",
                       verdict, recommendation, corrected)
        recommendation = corrected

    if not findings:
        findings = [{
            "claim": "근거 조항과 연결된 판단을 만들지 못했습니다.",
            "reasoning": "검색된 규정·사례로는 이 거래를 판단할 근거를 찾지 못했습니다. "
                         "아래 참고 사항과 거래 내역을 직접 확인해 주세요.",
            "evidence": [],
        }]

    return {
        "summary": report.summary,
        "recommendation": recommendation,
        "highlights": list(report.highlights),
        "findings": findings,
        "advisories": advisories,
    }


def _fallback_report(classification: dict, reason: str) -> dict:
    """보고서 LLM이 실패했을 때 — **이미 확보한 분류 결과를 버리지 않는다.**

    ①분류는 근거 검색까지 마쳐 비용을 이미 지불했다. 여기서 예외를 올리면 그게 통째로
    사라지고 Django엔 `RiskReview` 행이 안 남는다(검토자 화면엔 「AI가 아무것도 안 했다」).
    """
    verdict = classification.get("violation_verdict", "")
    reasons = classification.get("review_reasons") or []
    return {
        "summary": f"보고서를 생성하지 못했습니다 — {reason}. 아래 검토 사유와 근거를 직접 확인해 주세요.",
        "recommendation": _ACTION_FALLBACK.get(verdict, "SUPPLEMENT"),
        "highlights": [],
        "findings": [{
            "claim": "; ".join(reasons) if reasons else "내규 검증 결과를 요약하지 못했습니다.",
            "reasoning": "보고서 작성 단계가 실패해 검증 결과만 그대로 옮깁니다.",
            "evidence": [],
        }],
        "advisories": ["AI 보고서 없이 사람이 직접 검토해야 하는 건입니다."],
    }


MAX_REPORT_ATTEMPTS = 2  # 첫 호출 + 피드백 재시도 1회. 그 이상은 비용만 늘고 안 나아졌다.


def _report_problems(report: RiskReport, classification: dict, index: dict[str, dict]) -> list[str]:
    """보고서를 **되돌려 보낼 이유**만 모은다 — 고쳐 쓰면 나아지는 것들.

    `_validate_report`가 하는 일과 다르다. 저쪽은 「그대로 쓸 수 없는 부분을 서버가
    걷어내는」 최종 방어이고, 여기는 **모델에게 다시 시킬 값어치가 있는가**를 본다.
    그래서 강등으로 해결되는 것(근거 없는 finding → advisories)은 문제로 세지 않는다.
    """
    problems: list[str] = []
    verdict = classification.get("violation_verdict", "")

    allowed = _ALLOWED_RECOMMENDATION.get(verdict)
    if allowed and report.recommendation not in allowed:
        problems.append(
            f"위반 여부 분류가 {verdict}인데 권장 처리를 {report.recommendation}로 냈습니다. "
            f"이 분류에서 낼 수 있는 값은 {' 또는 '.join(allowed)} 뿐입니다. "
            "위반 여부를 다시 판단하지 말고 분류 결과를 그대로 따르세요."
        )

    unknown = sorted({e.ref for f in report.findings for e in f.evidence if e.ref not in index})
    if unknown:
        problems.append(
            f"근거 목록에 없는 id를 인용했습니다: {', '.join(unknown)}. "
            "제시된 근거 목록의 id만 그대로 쓰세요."
        )

    if not report.summary.strip():
        problems.append("요약(summary)이 비어 있습니다. 2문장 이내로 채우세요.")

    #  근거가 하나도 안 붙은 보고서는 화면에서 「검증 안 함」과 구분되지 않는다.
    #  다만 **줄 근거가 애초에 없었다면** 모델 잘못이 아니므로 되돌리지 않는다.
    if index and not any(e.ref in index for f in report.findings for e in f.evidence):
        problems.append(
            "근거를 하나도 인용하지 않았습니다. 최소 한 개의 finding에 "
            "제시된 근거 목록의 id를 붙이세요."
        )
    return problems


def _build_report(summary: dict, stage1: dict, classification: dict, profile: str) -> dict:
    """②보고서: 분류 결과 + 거래 사실 → 담당자가 읽는 산출물.

    **검증 → 재작성 루프**를 돈다(Rule Agent의 재생성 루프와 같은 모양). 되돌려 보낼 때
    바뀌는 것은 「무엇이 왜 틀렸는가」뿐이고, 근거·사실은 그대로 재사용한다.

    권장 처리는 **세 겹으로** 잠근다 — ① 출력 스키마에서 낼 수 없는 값을 뺀다
    ② 프롬프트가 허용 값을 명시한다 ③ 그래도 어긋나면 서버가 되돌린다(`_validate_report`).
    ①이 정본이고 ②③은 그물이다.
    """
    pool, index = _evidence_pool(classification)
    notable_facts = notables(summary.get("evalContext") or {}, summary.get("ruleFlags") or [])
    note = f"— {stage1['note']}" if stage1.get("note") else ""
    user_prompt = _REPORT_USER_PROMPT_TEMPLATE.format(
        violation_verdict=classification.get("violation_verdict", ""),
        review_reasons="; ".join(classification.get("review_reasons") or []) or "(없음)",
        anomaly_score=f"{stage1.get('anomaly_score', 0.0):.3f}",
        risk_tier=stage1.get("risk_tier") or "미측정",
        anomaly_note=note,
        merchant=summary["merchant"],
        amount=summary["amount"],
        category=summary["category"],
        purpose=summary.get("purpose") or "(미기재)",
        facts=facts_nl(summary) or "(없음)",
        #  무엇이 눈여겨볼 만한지는 **코드가** 고른다 — 54개 경로를 그대로 던지면 모델이
        #  아무거나 고르고, 대개 화면에 이미 있는 금액·시각을 고른다(`review_notables`).
        notables="\n".join(f"- {n}" for n in notable_facts) or "(없음)",
        evidence_pool=pool,
        allowed_recommendation=" 또는 ".join(
            _ALLOWED_RECOMMENDATION.get(classification.get("violation_verdict", ""), ())
        ) or "APPROVE 또는 SUPPLEMENT 또는 REJECT",
    )
    model_cls = _REPORT_MODEL.get(classification.get("violation_verdict", ""), RiskReport)

    report = None
    feedback = ""
    for attempt in range(1, MAX_REPORT_ATTEMPTS + 1):
        try:
            report, _ = llm.parse(
                profile,
                model=model_cls,
                schema_name="risk_report",
                messages=[
                    {"role": "system", "content": _REPORT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt + feedback},
                ],
                timeout=90,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("보고서 생성 실패(profile=%s, %d회차): %s — 분류 결과로 폴백",
                           profile, attempt, exc)
            return _fallback_report(classification, f"{type(exc).__name__}")

        problems = _report_problems(report, classification, index)
        if not problems:
            break
        if attempt == MAX_REPORT_ATTEMPTS:
            #  **여기서 버리지 않는다.** 남은 문제는 `_validate_report`가 강등·정정으로
            #  처리할 수 있는 것들이고, 보고서를 통째로 버리면 담당자는 빈손이 된다.
            logger.warning("보고서 재작성 %d회에도 남은 문제: %s — 서버 정정으로 넘긴다",
                           MAX_REPORT_ATTEMPTS, "; ".join(problems))
            break
        logger.info("보고서 재작성(%d회차) — %s", attempt + 1, "; ".join(problems))
        feedback = ("\n\n[직전 작성본의 문제 — 아래를 고쳐 다시 작성하세요]\n"
                    + "\n".join(f"- {p}" for p in problems))

    return _validate_report(report, classification, index)


#: 1차 이상탐지의 결과 상태. **점수 0과 "점수를 못 냈다"를 가르는 축**이다.
#   ok        정상 채점
#   no_model  학습된 모델이 없다(경로 어긋남·미배치)
#   error     피처 조립·추론 실패
STAGE1_OK, STAGE1_NO_MODEL, STAGE1_ERROR = "ok", "no_model", "error"


def _stage1_unavailable(status: str, message: str) -> dict:
    """채점하지 못했다 — **판정처럼 보이는 값을 채우지 않는다.**

    예전엔 `risk_tier="LOW"`를 돌려줬다. 화면은 그걸 「이상 신호 낮음」으로 읽으므로,
    모델이 없어서 못 잰 건이 **검사해보니 안전한 건**으로 둔갑했다. 등급은 빈 문자열로
    둔다 — 저장소에 이미 `riskTier: '' = 판단 없음` 계약이 있다(`ReviewItem`).

    `anomaly_score`는 0.0을 유지하되(필드 타입이 float다) `status`가 그 0이 점수가 아님을
    말한다. 화면은 `status`를 보고 `-`로 그린다.
    """
    return {
        "anomaly_score": 0.0,
        "is_outlier": False,
        "contribs": [],
        "risk_tier": "",
        "status": status,
        "note": message,
    }


def _stage1(tx_id: int) -> dict:
    """1차 이상탐지: get_tx_features → ml_infer → risk_tier.

    모델이 없거나 실패하면 **채점하지 않았다는 사실을 명시해** 돌려준다(`_stage1_unavailable`).

    **실패해도 예외를 올리지 않는다.** 여기서 터지면 2차 RAG 내규검증까지 같이 죽는데, 2차는
    1차 결과 없이도 (근거 검색만으로) 충분히 돌아간다 — 실제로 현재 배포 모델은 contribs가
    상시 빈 배열이라 2차가 1차에 실질적으로 의존하지 않는다. 더 중요한 건 호출부다: Django
    `settlements/risk_review.py`는 이 요청이 실패하면 경고만 남기고 `RiskReview` 행을 **아예
    안 만든다** — 즉 `get_tx_features` 500 하나로 검토자 화면엔 "AI가 아무것도 안 했다"만
    남는다. 그래서 1차 실패는 stub+사유로 격하하고 2차는 계속 태운다(2026-08-19 실측 수정).
    """
    try:
        features = tools.get_tx_features(tx_id)
        model = get_active_model()
        if not model or not model.fitted:
            #  **조용히 넘어가지 않는다.** 로그가 없으면 "모델을 넣었는데 왜 점수가 0인가"를
            #  추적할 수 없다(경로가 어긋나 못 찾고 있어도 화면엔 정상처럼 보인다).
            #  찾던 경로는 레지스트리가 찍는다.
            logger.warning("stage1(이상탐지) 미실행 — 학습된 모델이 없다(tx=%s)", tx_id)
            return _stage1_unavailable(
                STAGE1_NO_MODEL,
                "학습된 이상탐지 모델이 없어 위험 점수를 계산하지 못했습니다.",
            )
        result = tools.ml_infer(features["feature_vector"])
        result["risk_tier"] = _risk_tier(result.get("anomaly_score", 0.0))
        result["status"] = STAGE1_OK
        if _tier_override():
            #  화면·보고서·평가 결과 어디서든 「강제된 등급」임을 알 수 있어야 한다.
            result["note"] = (f"등급이 {result['risk_tier']}로 강제 고정된 상태입니다"
                              " (RISK_TIER_OVERRIDE) — 점수로 정해진 등급이 아닙니다.")
            result["tier_forced"] = True
        return result
    except Exception as exc:  # noqa: BLE001  # Django 미기동·형상 불일치·모델 로드 실패 전부
        logger.warning("stage1(이상탐지) 실패(tx=%s): %s — 2차 검증만 진행", tx_id, exc)
        return _stage1_unavailable(
            STAGE1_ERROR,
            f"이상탐지 실행에 실패해 위험 점수를 계산하지 못했습니다 ({type(exc).__name__}).",
        )


#: 1차 등급 → 2차 처리. **위험이 높을수록 비싼 모델**을 쓴다.
#   LOW     심층 검증을 하지 않는다(LLM 0회). 고정 안내 + 승인 추천.
#   MEDIUM  fast  프로파일로 심층 검증
#   HIGH    heavy 프로파일로 심층 검증
#   미측정  heavy — **못 잰 것을 싸게 넘기지 않는다.** 모델이 없어 등급이 없는 건을 LOW로
#           접으면 「검사해보니 일반 거래」가 되는데, 실제로는 검사를 못 한 것이다.
_TIER_PROFILE = {"HIGH": "heavy", "MEDIUM": "fast"}

LOW_TIER_SUMMARY = (
    "일반 거래로 분류되어 승인을 추천합니다. "
    "이상탐지에서 특이 신호가 발견되지 않아 내규 심층 검증은 수행하지 않았습니다."
)
LOW_TIER_ADVISORY = (
    "규정 대조를 거치지 않은 건입니다 — 필요하면 직접 확인하거나 심층 검토를 요청해 주세요."
)


def _low_tier_report(stage1: dict) -> dict:
    """【하】 등급 — **LLM을 부르지 않는다.**

    고정 문구라 지어낼 여지가 없고 비용·지연이 0이다. 중요한 건 문구가
    「검사해보니 문제없음」이 아니라 **「검사하지 않음」**이라고 말하는 것이다
    (`RulePassedNotice`와 같은 규율 — 검사 안 한 것과 통과는 다르다).
    """
    return {
        "violation_verdict": "NO_VIOLATION",
        "review_reasons": [],
        "recommendation": "APPROVE",
        "citations": [],
        "similar_cases": [],
        "tier_path": "low",
        "model": "",
        "report": {
            "summary": LOW_TIER_SUMMARY,
            "recommendation": "APPROVE",
            "highlights": [],
            "findings": [{
                "claim": "이상탐지에서 특이 신호가 발견되지 않았습니다.",
                "reasoning": f"위험 점수 {stage1.get('anomaly_score', 0.0):.3f}로 "
                             "일반 거래 구간에 속해 내규 심층 검증 대상이 아닙니다.",
                "evidence": [],
            }],
            "advisories": [LOW_TIER_ADVISORY],
        },
    }


def _stage2(summary: dict, stage1: dict) -> dict:
    """2차 — 등급에 따라 갈린다. 반환 shape은 기존 5개 필드 + `report`(확장만)."""
    tier = stage1.get("risk_tier") or ""
    scored = stage1.get("status", STAGE1_OK) == STAGE1_OK

    if scored and tier == "LOW":
        return _low_tier_report(stage1)

    #  등급이 없으면(미측정) heavy로 — 위 `_TIER_PROFILE` 주석 참조.
    profile = _TIER_PROFILE.get(tier, "heavy")
    logger.info("2차 심층 검증 시작 (tier=%s scored=%s profile=%s model=%s)",
                tier or "미측정", scored, profile, llm.model_of(profile))

    classification = _classify(summary, stage1, profile)
    report = _build_report(summary, stage1, classification, profile)
    return {
        "violation_verdict": classification["violation_verdict"],
        "review_reasons": classification["review_reasons"],
        #  권장 처리의 정본은 **보고서**다 — 담당자가 읽는 문장과 다른 값이 저장되면 안 된다.
        "recommendation": report["recommendation"],
        "citations": classification["citations"],
        "similar_cases": classification["similar_cases"],
        "tier_path": profile,
        "model": llm.model_of(profile),
        "report": report,
    }


def run(settlement_id: int) -> dict:
    try:
        summary = core_client.get_settlement_summary(settlement_id)
    except Exception as exc:  # noqa: BLE001  # Django 미기동 등 — 1차만이라도 stub으로 응답
        logger.warning("get_settlement_summary(%s) 실패: %s", settlement_id, exc)
        return {
            "settlement_id": settlement_id,
            "stage1_anomaly": _stage1_unavailable(
                STAGE1_ERROR,
                f"정산 정보를 읽지 못해 이상탐지를 실행하지 못했습니다 ({type(exc).__name__}).",
            ),
            "stage2_rag_review": {
                "violation_verdict": "INSUFFICIENT_INFO",
                "review_reasons": [f"정산 조회 실패: {type(exc).__name__}"],
                "recommendation": "SUPPLEMENT", "citations": [], "similar_cases": [],
            },
            "status": "error",
        }

    stage1 = _stage1(summary["tx_id"])
    stage2 = _stage2(summary, stage1)

    return {
        "settlement_id": settlement_id,
        "stage1_anomaly": stage1,
        "stage2_rag_review": stage2,
        "status": "ok",
    }
