"""③ Risk Review Agent — MVP 2단계 (요구사항 §5.5 / 기술명세서 §4.3).

  [1차] 단순 이상거래 탐지(비지도) → anomaly_score + feature_contribs + risk_tier(3단계)
  [2차] RAG 내규 기반 검증 — ①분류(위반 여부) → ②액션(권장 처리) 2단, MCP 툴콜링(§1)

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
  3. **분류(violation_verdict) ↔ 액션(recommendation) 단계 분리** — 이전엔 한 번의 LLM
     호출·한 스키마(`RiskVerdict`)가 위반 여부와 권장 처리를 동시에 냈다. v1은 ①분류
     호출(근거 검색 포함, MCP 툴콜링)이 끝난 뒤 ②액션 호출(분류 결과만 입력받아 권장
     처리 결정)로 나눈다 — 판단(사실관계)과 처리방침(정책적 선택)을 같은 근거 확보
     루프에 묶지 않기 위함. **반환 계약(dict shape)은 그대로 유지**(§3 비침습 체크리스트) —
     `stage2_rag_review`의 5개 필드(violation_verdict/review_reasons/recommendation/
     citations/similar_cases)는 이전과 동일하게 채워진다.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Literal

from openai import OpenAI
from pydantic import BaseModel

from app.agents import mcp_client
from app.clients import core_client
from app.config import settings
from app.mcp import tools
from app.ml.registry import get_active_model
from app.rag.retrieval import build_query, facts_nl

# 4629076 이후 main에서 병합된 리트리벌 품질 개선(2026-08-19, c605e99/21ffe4f)을 이 v1
# 재작성 위에 그대로 접목한다 — ① build_query(자연어 질의+facts_nl, 원시 피처명 노출 금지,
# ΔMRR +0.020 실측) ② _format_policy_chunks의 parent_text(같은 조 전문) 포함 ③ 분류
# 프롬프트의 "확정 판정엔 유보 표현 금지" 규칙.

logger = logging.getLogger(__name__)

MODEL = "gpt-4o-mini"

# risk_tier 고정 임계값(모듈 docstring 참조) — 배포된 anomaly.pkl 실측 기준, 재학습해도
# 자동 갱신 안 됨. anomaly_score >= HIGH: 상위 10분위(관측 이상비율 급등 구간),
# MEDIUM <= score < HIGH: 기존 운영 is_outlier 컷오프~HIGH 사이, 그 미만은 LOW.
RISK_TIER_HIGH_THRESHOLD = 0.0134
RISK_TIER_MEDIUM_THRESHOLD = 0.0037

MAX_TOOL_TURNS = 6  # §1 항목1과 동일한 안전판 근거(search 2~3회 + 최종 제출 여유)

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


def _risk_tier(anomaly_score: float) -> Literal["HIGH", "MEDIUM", "LOW"]:
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


class ActionDecision(BaseModel):
    """②액션 단계 산출물 — 분류 결과를 입력받아 권장 처리만 결정."""
    recommendation: Literal["APPROVE", "SUPPLEMENT", "REJECT"]
    rationale: str


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

[검토 대상 거래]
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


def _classify(summary: dict, stage1: dict) -> dict:
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
    initial_policy = _safe_search("search_policy", "chunks", query=initial_query, top_k=6, rerank=True)
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
        resp = _get_client().chat.completions.create(
            model=MODEL,
            temperature=0.2,
            timeout=30,
            tools=tool_specs,
            tool_choice="auto",
            messages=messages,
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
                    rerank=True,
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

_ACTION_SYSTEM_PROMPT = """당신은 법인카드 정산 Risk Review의 처리방침 담당입니다. 앞 단계에서
이미 확정된 "내규 위반 여부 분류" 결과만 보고, 권장 처리(recommendation)를 결정하세요.
위반 여부 자체를 재판단하거나 뒤집지 마세요 — 주어진 분류를 그대로 전제로 합니다.

규칙:
- violation_verdict가 VIOLATION이면 REJECT 또는 SUPPLEMENT(보완요청) 중 사안의 심각도에
  맞게 고르세요(위반이 명백하고 시정 불가능하면 REJECT, 소명/보완으로 해소 가능하면 SUPPLEMENT).
- violation_verdict가 NO_VIOLATION이면 APPROVE.
- violation_verdict가 INSUFFICIENT_INFO면 사람 판단이 필요하므로 원칙적으로 SUPPLEMENT.
- rationale은 1~2문장으로, review_reasons에 근거해 왜 이 처리를 권장하는지 설명하세요."""

_ACTION_USER_PROMPT_TEMPLATE = """[분류 결과]
violation_verdict: {violation_verdict}
review_reasons: {review_reasons}
citations: {citations}

recommendation을 결정하세요."""


# 액션 LLM이 실패했을 때 쓰는 결정론적 폴백 — 프롬프트 규칙의 "안전한 쪽" 절반만 남긴 것.
# **VIOLATION이어도 REJECT로 자동 강등하지 않는다**: 최종반려는 되돌릴 수 없는 단말이라
# 사람(회계 담당자)만 내릴 수 있다는 도메인 원칙(CLAUDE.md — "엔진은 최종반려를 만들지
# 않는다" / "사람 확정 원칙")을 LLM 장애 경로에서도 그대로 지킨다.
_ACTION_FALLBACK = {
    "NO_VIOLATION": "APPROVE",
    "VIOLATION": "SUPPLEMENT",
    "INSUFFICIENT_INFO": "SUPPLEMENT",
}


def _decide_action(classification: dict) -> dict:
    """②액션: 단일 호출(근거 검색 불필요 — 분류 단계에서 이미 확보된 근거만 본다).

    **분류 결과를 유실시키지 않는다.** 여기서 예외를 올리면 이미 성공한 ①분류(근거 검색·인용
    포함, 비용도 이미 지불)까지 통째로 버려지고 Django엔 `RiskReview` 행이 안 남는다. 그래서
    LLM 장애는 결정론적 폴백으로 격하하고, 폴백을 썼다는 사실을 `rationale`에 남긴다.
    """
    verdict = classification["violation_verdict"]
    user_prompt = _ACTION_USER_PROMPT_TEMPLATE.format(
        violation_verdict=verdict,
        review_reasons="; ".join(classification.get("review_reasons") or []) or "(없음)",
        citations=", ".join(
            f"「{c['doc']}」{c['article']}" for c in classification.get("citations") or []
        ) or "(없음)",
    )
    try:
        resp = _get_client().beta.chat.completions.parse(
            model=MODEL,
            temperature=0.2,
            timeout=30,
            messages=[
                {"role": "system", "content": _ACTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format=ActionDecision,
        )
        parsed = resp.choices[0].message.parsed
    except Exception as exc:  # noqa: BLE001  # OpenAI 장애·타임아웃 등
        logger.warning("액션 단계 LLM 실패(%s) — 결정론적 폴백 사용: %s", verdict, exc)
        parsed = None

    if parsed is None:
        return {
            "recommendation": _ACTION_FALLBACK.get(verdict, "SUPPLEMENT"),
            "rationale": "권장 처리를 LLM으로 판단하지 못해 안전한 기본값을 적용했습니다 — 사람 검토 필요",
        }
    return parsed.model_dump()


def _stage1(tx_id: int) -> dict:
    """1차 이상탐지: get_tx_features → ml_infer → risk_tier. 모델 미학습이면 stub 그대로 통과.

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
            return {
                "anomaly_score": 0.0, "is_outlier": False, "contribs": [],
                "risk_tier": "LOW", "note": "no trained model (stub)",
            }
        result = tools.ml_infer(features["feature_vector"])
        result["risk_tier"] = _risk_tier(result.get("anomaly_score", 0.0))
        return result
    except Exception as exc:  # noqa: BLE001  # Django 미기동·형상 불일치·모델 로드 실패 전부
        logger.warning("stage1(이상탐지) 실패(tx=%s): %s — 2차 검증만 진행", tx_id, exc)
        return {
            "anomaly_score": 0.0, "is_outlier": False, "contribs": [],
            "risk_tier": "LOW", "note": f"stage1 실패({type(exc).__name__}) — 이상탐지 결과 없음",
        }


def _stage2(summary: dict, stage1: dict) -> dict:
    """2차 RAG 내규 검증 — ①분류(MCP 툴콜링) → ②액션(권장 처리). 반환 shape은 v0과 동일."""
    classification = _classify(summary, stage1)
    action = _decide_action(classification)
    return {
        "violation_verdict": classification["violation_verdict"],
        "review_reasons": classification["review_reasons"],
        "recommendation": action["recommendation"],
        "citations": classification["citations"],
        "similar_cases": classification["similar_cases"],
    }


def run(settlement_id: int) -> dict:
    try:
        summary = core_client.get_settlement_summary(settlement_id)
    except Exception as exc:  # noqa: BLE001  # Django 미기동 등 — 1차만이라도 stub으로 응답
        logger.warning("get_settlement_summary(%s) 실패: %s", settlement_id, exc)
        return {
            "settlement_id": settlement_id,
            "stage1_anomaly": {
                "anomaly_score": 0.0, "is_outlier": False, "contribs": [],
                "risk_tier": "LOW", "note": "stub",
            },
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
