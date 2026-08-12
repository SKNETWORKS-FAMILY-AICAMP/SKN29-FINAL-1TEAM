"""구조 기반 청킹 — `llm_wiki/_context/chunking-strategy.md`.

`ParsedDoc`(파싱 산출물) → `Chunk[]`(검색 단위). 임베딩·Chroma upsert는 여기 없다 —
임베딩 모델이 확정되면 `embeddings.py`가 `Chunk.embedding_text()`를 태워 붙인다.
"""
from app.rag.chunking.chunker import chunk_document
from app.rag.chunking.model import Budget, Chunk, ChunkReport, DEFAULT_BUDGET

__all__ = ["chunk_document", "Budget", "Chunk", "ChunkReport", "DEFAULT_BUDGET"]
