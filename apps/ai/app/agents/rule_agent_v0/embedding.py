# apps/ai/app/agents/rule_agent_v0/embedding.py
"""OpenAI 임베딩 클라이언트 — `embedding-strategy.md` §1 고정 계약.

계약(변경 금지, 변경 시 embedding-strategy.md 개정 선행):
  - 모델: text-embedding-3-large, dimensions=1024
  - 문서 입력: Chunk.embedding_text() (계층 헤더 + 본문) — 호출측 책임
  - 질의 입력: "사내 규정 조문 검색: {질의}" 접두
  - 정규화: L2 1회 (저장/질의 직전)
  - 배치: 128

v1 참고: 이 계약(모델/차원/접두/정규화)은 컬렉션 전체(Draft·Risk Agent 포함)가
공유해야 재현성이 유지된다. v0 통합 시 중앙 `app/rag/`로 승격 권장(GAPS 참조).
"""
from __future__ import annotations

import math

from openai import OpenAI

from .settings import settings

EMBED_MODEL = "text-embedding-3-large"
EMBED_DIM = 1024
QUERY_PREFIX = "사내 규정 조문 검색: "
BATCH_SIZE = 128

_client = OpenAI(api_key=settings.openai_api_key)


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def embed_texts(texts: list[str]) -> list[list[float]]:
    """문서 청크 임베딩(배치). 입력은 embedding_text() 결과여야 한다."""
    out: list[list[float]] = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        resp = _client.embeddings.create(
            model=EMBED_MODEL, input=batch, dimensions=EMBED_DIM
        )
        out.extend(_l2_normalize(d.embedding) for d in resp.data)
    return out


def embed_query(query: str) -> list[float]:
    """질의 임베딩 — Q_ctx 접두 규약 적용."""
    resp = _client.embeddings.create(
        model=EMBED_MODEL, input=[QUERY_PREFIX + query], dimensions=EMBED_DIM
    )
    return _l2_normalize(resp.data[0].embedding)
