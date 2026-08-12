"""임베딩 · Chroma 적재 — `llm_wiki/_context/embedding-strategy.md`.

파싱(`ParsedDoc`) → 청킹(`Chunk[]`) 다음 칸. 청킹이 벡터 스토어에 직접 붙지 않으므로
Chroma 어댑터는 여기 한 층에만 있다.
"""
from app.rag.embedding.config import (
    ALL_COLLECTIONS,
    COLLECTION_OF,
    DEFAULT,
    JUDGEMENT_COLLECTIONS,
    EmbeddingConfig,
)
from app.rag.embedding.encoder import OpenAIEncoder
from app.rag.embedding.store import (
    UpsertReport,
    collection_for,
    get_client,
    get_collection,
    peek,
    search,
    upsert_chunks,
)

__all__ = [
    "ALL_COLLECTIONS",
    "COLLECTION_OF",
    "DEFAULT",
    "JUDGEMENT_COLLECTIONS",
    "EmbeddingConfig",
    "OpenAIEncoder",
    "UpsertReport",
    "collection_for",
    "get_client",
    "get_collection",
    "peek",
    "search",
    "upsert_chunks",
]
