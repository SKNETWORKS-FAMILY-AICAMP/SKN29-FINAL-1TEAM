# apps/ai/app/agents/rule_agent_v0/vector_store.py
"""Chroma 접근 계층 — 기술명세서 §5.1: 벡터 데이터는 tool이 Chroma에 직접 접근.

컬렉션명은 `policy_docs`를 그대로 쓴다(스펙상의 실제 컬렉션명, v0 전용 샌드박스가
아님) — v1에서 이 모듈이 중앙으로 승격되더라도 데이터 마이그레이션이 필요 없다.
"""
from __future__ import annotations

from typing import Any

import chromadb

from .settings import settings

COLLECTION_POLICY_DOCS = "policy_docs"

_client: chromadb.ClientAPI | None = None


def get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        if settings.chroma_host:
            _client = chromadb.HttpClient(
                host=settings.chroma_host, port=settings.chroma_port
            )
        else:
            _client = chromadb.PersistentClient(path=settings.chroma_path)
    return _client


def get_policy_collection():
    return get_client().get_or_create_collection(
        name=COLLECTION_POLICY_DOCS, metadata={"hnsw:space": "cosine"}
    )


def upsert_chunks(
    ids: list[str],
    documents: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict[str, Any]],
) -> int:
    """doc_id가 파일 해시라 내용이 같으면 같은 ID → upsert가 곧 멱등 재인덱싱."""
    col = get_policy_collection()
    col.upsert(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)
    return len(ids)


def query_policy(
    query_embedding: list[float], top_k: int = 6, where: dict | None = None
) -> list[dict[str, Any]]:
    col = get_policy_collection()
    res = col.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    out = []
    for i, chunk_id in enumerate(res["ids"][0]):
        out.append(
            {
                "chunk_id": chunk_id,
                "text": res["documents"][0][i],
                "metadata": res["metadatas"][0][i],
                "distance": res["distances"][0][i],
            }
        )
    return out
