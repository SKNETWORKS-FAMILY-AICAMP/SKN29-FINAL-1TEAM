"""검색 결과 재선별(LLM rerank) — 벡터 top-k 다음 층.

벡터 유사도는 "질의와 비슷한 화제"를 고르지 "질의에 실제로 답하는 조항"을 고르지 않는다.
`query_builder.py`가 고정 문구 "위반"을 뺀 것도 이 문제의 한 증상(무관한 "위반 시 조치"
조항으로 쏠림)이었을 뿐 — 화제가 겹치면 실제로 그 질문에 답하는지와 무관하게 상위로
뽑히는 것은 벡터검색 자체의 한계라 문구 하나로는 못 없앤다. 이 모듈은 vector search가
top_k보다 넉넉히 뽑아온 후보를 LLM이 걸러 실제로 쓸모있는 것만 남긴다(재현율 우선 지시 —
애매하면 포함, 명백히 무관하면 제외).

**실패는 "근거 없음"으로 접지 않는다.** LLM이 명시적으로 "관련 없는 후보"라 답한 것과
rerank 호출 자체가 실패(타임아웃·API 오류)한 것은 다른 상황이다 — 후자를 빈 배열로
접으면 "검색 결과가 원래 없었다"와 구분이 안 돼 하류(Risk Review 등)가 INSUFFICIENT_INFO로
잘못 수렴한다. 그래서 호출 실패는 원본 후보를 top_n만큼 그대로 반환한다(fail-open).
"""
from __future__ import annotations

import logging

from openai import OpenAI
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

MODEL = "gpt-4o-mini"

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


class RerankVerdict(BaseModel):
    relevant_chunk_ids: list[str]  # 관련도 높은 순. 실제로 질의에 답하는 게 없으면 빈 배열.


SYSTEM_PROMPT = """당신은 사내 규정 검색 결과의 재선별 담당입니다. 벡터 유사도로 뽑힌
후보 조각들 중, 아래 질의에 실제로 답하는 데 쓸 수 있는 것만 골라 관련도 높은 순으로
나열하세요.

규칙:
1. 화제만 비슷하고 질의에 실제로 답하지 않는 조각은 제외하세요(예: 질의가 한도 금액을
   묻는데 "위반 시 조치"·"정의" 조항만 있는 경우).
2. 판단이 애매하면 포함하는 쪽을 택하세요(재현율 우선) — 명백히 무관한 것만 제외합니다.
3. 근거로 쓸 만한 조각이 하나도 없으면 빈 배열을 반환하세요. 억지로 채우지 마세요.
4. chunk_id는 후보 목록에 있는 값을 그대로 쓰세요 — 지어내지 마세요."""

USER_PROMPT_TEMPLATE = """[질의]
{query}

[후보 조각]
{candidates}"""


def _format_candidates(hits: list[dict]) -> str:
    lines = []
    for h in hits:
        text = (h.get("text") or h.get("document") or "")[:300]
        lines.append(f"- chunk_id={h['chunk_id']} | {h.get('citation')}: {text}")
    return "\n".join(lines)


def rerank(query: str, hits: list[dict], top_n: int) -> list[dict]:
    """후보 `hits`(정본 검색 결과, dict 형태 그대로) 중 질의에 실제로 답하는 것만 top_n개.

    입력 dict를 그대로 골라 반환한다(reorder·필터만, 필드 가공 없음) — 이후 포맷팅
    (`risk_review_agent._format_chunks` 등)이 그대로 재사용된다.
    """
    if not hits:
        return []

    user_prompt = USER_PROMPT_TEMPLATE.format(query=query, candidates=_format_candidates(hits))
    try:
        resp = _get_client().beta.chat.completions.parse(
            model=MODEL,
            temperature=0.0,
            timeout=15,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format=RerankVerdict,
        )
        parsed = resp.choices[0].message.parsed
    except Exception as exc:  # noqa: BLE001  # rerank 인프라 장애는 재선별 실패일 뿐 검색 실패가 아니다
        logger.warning("rerank 호출 실패, 원본 top_n으로 폴백: %s", exc)
        return hits[:top_n]

    if parsed is None:
        logger.warning("rerank 구조화 응답 없음, 원본 top_n으로 폴백")
        return hits[:top_n]

    by_id = {h["chunk_id"]: h for h in hits}
    selected = [by_id[cid] for cid in parsed.relevant_chunk_ids if cid in by_id]
    return selected[:top_n]
