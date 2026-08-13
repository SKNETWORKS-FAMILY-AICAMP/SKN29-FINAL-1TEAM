# apps/ai/app/agents/rule_agent_v0/search.py
"""search_policy 구현 — v0는 기존 `mcp/tools.py`를 거치지 않고 이 함수를
rule_agent_v0 내부에서 직접 호출한다(격리 우선, MCP 계층 미변경).

⚠️ v1로 승격 시 반드시 `mcp/tools.py`의 `search_policy` stub을 이 로직으로
교체해야 한다 — 그래야 Risk Review Agent도 같은 tool을 통해 동일한 로깅·
검색 경로를 공유한다(§5 설계 규칙 "모든 tool call 로깅"). v0 상태로는
tool call 로그에 잡히지 않는다 — GAPS 참조.
"""
from __future__ import annotations

from typing import Any

from .embedding import embed_query
from .vector_store import query_policy


def search_policy(
    query: str, top_k: int = 6, where: dict | None = None
) -> list[dict[str, Any]]:
    """규정 조항 검색. 반환 청크에는 citation(「문서명」 제N조 …)이 항상 포함된다.

    citation 원천은 청크 메타(chunking-strategy §8.2). 메타에 없으면
    doc_name + article_label로 조립해 폴백한다.
    """
    q_emb = embed_query(query)
    hits = query_policy(q_emb, top_k=top_k, where=where)
    for h in hits:
        meta = h.get("metadata") or {}
        citation = meta.get("citation")
        if not citation:
            citation = " ".join(
                s for s in [meta.get("doc_name"), meta.get("article_label")] if s
            )
        h["citation"] = citation or h["chunk_id"]
    return hits
