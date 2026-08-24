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

from app.clients import core_client
from app.rag.embedding import store
from app.rag.retrieval.rerank import rerank as _rerank

# 규정 우선. 세법(tax_refs)은 조문 자체가 룰이 되기보다 근거 보강이라 옵션으로 둔다.
POLICY_COLLECTION = "policy_docs"
LAW_COLLECTION = "tax_refs"

# rerank=True일 때 top_k보다 얼마나 넉넉히 뽑을지. LLM이 실제로 고를 여지를 주되
# 프롬프트가 무한정 커지지 않게 상한을 둔다.
_RERANK_OVERFETCH = 3
_RERANK_MAX_CANDIDATES = 20


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
    query: str, top_k: int = 6, *, include_law: bool = False, rerank: bool = False,
    scope: str | None = None,
) -> list[dict[str, Any]]:
    """규정 조항 검색. 반환 청크에는 citation(「문서명」 제N조 …)이 항상 포함된다.

    `include_law=True`면 세법(`tax_refs`)도 같은 질의로 검색해 유사도 순으로 합친다.
    두 컬렉션은 같은 임베딩 신원(`3-large@1024`)을 쓰므로 점수를 직접 비교해도 된다.

    `scope`를 주면 그 카테고리(+공통 규정) 문서에서만 찾는다(Django `PolicyDoc.rule_scope`
    조회, `core_client.get_policy_doc_names`). **컬렉션 전체를 뒤지면 카테고리가 새어
    들어온다** — QA 2026-08-24 실측: 회식 규정이 식대 거래·회의 카테고리 질의에 오적용됨.
    `scope=None`이거나 매핑 조회가 실패하면(빈 리스트) 이전처럼 전체 검색으로 fail-open —
    필터 장애가 검색 자체를 막지 않는다. `include_law=True`일 때 법령(`tax_refs`)에는
    scope 필터를 걸지 않는다(세법은 카테고리 구분 없이 공통 참고 자료라서다).

    `rerank=True`면 벡터 top-k를 그대로 쓰지 않는다 — top_k보다 넉넉히 뽑아 LLM이
    질의에 실제로 답하는 것만 추려 top_k로 좁힌다(`rag/retrieval/rerank.py`). 벡터
    유사도는 화제가 같으면 뽑지 질의에 답하는지는 모르기 때문 — LLM 호출 1회가 붙는
    대가로 근거 정밀도를 올린다.
    """
    fetch_k = min(top_k * _RERANK_OVERFETCH, _RERANK_MAX_CANDIDATES) if rerank else top_k
    doc_names = core_client.get_policy_doc_names(scope) if scope else []
    hits = [
        _normalize(h, POLICY_COLLECTION)
        for h in store.search(
            query, collection_name=POLICY_COLLECTION, top_k=fetch_k, doc_names=doc_names or None,
        )
    ]
    if include_law:
        hits += [
            _normalize(h, LAW_COLLECTION)
            for h in store.search(query, collection_name=LAW_COLLECTION, top_k=fetch_k)
        ]
        hits.sort(key=lambda h: h["score"] if h["score"] is not None else -1, reverse=True)
        hits = hits[:fetch_k]
    if rerank:
        hits = _rerank(query, hits, top_n=top_k)
    return hits
