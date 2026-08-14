# apps/ai/app/agents/rule_agent_v0/search.py
"""규정 조항 검색 — 팀 RAG 정본(`app.rag.embedding.store`)을 그대로 쓴다.

**여기에 임베딩·Chroma 접근 사본을 두지 않는다.** v0는 자체 `embedding.py`/
`vector_store.py`를 갖고 있었는데, 그 사본이 정본과 세 곳에서 달랐고 전부 검색 품질을
깎았다:

  ① 부모 청크를 걸러내지 않았다 — 부모는 조 전문이라 **무엇과도 어중간하게 닮아**
     top-k를 잠식한다(정본 `store.search`는 `chunk_role != parent`로 뺀다).
  ② 부모 확장이 없었다 — 잎만 LLM에 넘겨 조 전체 맥락이 빠졌다.
  ③ `embedding_function=None`을 안 줘서, upsert가 컬렉션을 먼저 만들면 저장 문서로
     벡터를 다시 계산하는 사고가 가능했다(정본이 "계약의 핵심"이라 못 박은 것).

컬렉션 라우팅도 정본을 따른다 — 사내 규정은 `policy_docs`, 세법은 `tax_refs`,
조직도(`org_docs`)는 **판정 근거로 인용하지 않으므로 검색 대상이 아니다**
(`embedding/config.py`의 `COLLECTION_OF`·`JUDGEMENT_COLLECTIONS` 주석 참조).

⚠️ v1: `mcp/tools.py`의 `search_policy` stub이 이 함수를 부르도록 이관하면 Risk
Review Agent와 tool call 로깅 경로를 공유한다(GAPS G-7).
"""
from __future__ import annotations

from typing import Any

from app.rag.embedding import store

# 규정 우선. 세법(tax_refs)은 조문 자체가 룰이 되기보다 근거 보강이라 옵션으로 둔다.
POLICY_COLLECTION = "policy_docs"
LAW_COLLECTION = "tax_refs"


def _normalize(hit: dict[str, Any], collection: str) -> dict[str, Any]:
    """정본 hit → 프롬프트가 쓰는 모양. citation은 메타에 있는 게 원칙이고,
    없을 때만 문서명+조 라벨로 조립한다(빈 인용으로 LLM이 출처를 지어내지 않도록)."""
    meta = hit.get("metadata") or {}
    citation = hit.get("citation") or meta.get("citation")
    if not citation:
        citation = " ".join(
            s for s in [meta.get("doc_name"), meta.get("article_label")] if s
        ) or hit["chunk_id"]
    return {
        "chunk_id": hit["chunk_id"],
        "citation": citation,
        "text": hit.get("document") or "",
        # 부모(조 전문) — 있으면 프롬프트에 함께 실어 항 단위 조각의 맥락을 채운다.
        "parent_text": hit.get("parent_document") or "",
        "score": hit.get("score"),
        "collection": collection,
        "metadata": meta,
    }


def search_policy(
    query: str, top_k: int = 6, *, include_law: bool = False
) -> list[dict[str, Any]]:
    """규정 조항 검색. 반환 청크에는 citation(「문서명」 제N조 …)이 항상 포함된다.

    `include_law=True`면 세법(`tax_refs`)도 같은 질의로 검색해 유사도 순으로 합친다.
    두 컬렉션은 같은 임베딩 신원(`3-large@1024`)을 쓰므로 점수를 직접 비교해도 된다.
    """
    hits = [
        _normalize(h, POLICY_COLLECTION)
        for h in store.search(query, collection_name=POLICY_COLLECTION, top_k=top_k)
    ]
    if include_law:
        hits += [
            _normalize(h, LAW_COLLECTION)
            for h in store.search(query, collection_name=LAW_COLLECTION, top_k=top_k)
        ]
        hits.sort(key=lambda h: h["score"] if h["score"] is not None else -1, reverse=True)
        hits = hits[:top_k]
    return hits
