# apps/ai/app/agents/rule_agent_v0/api.py
"""v0 전용 라우터. 엔드포인트를 `/agent/rule-v0/...` 네임스페이스에 격리해
기술명세서 §6.2의 정식 엔드포인트(`/agent/rule/generate`)와 경로가 겹치지 않는다.

v1에서 이 로직이 검증되면 `/agent/rule/generate`로 승격하고 이 라우터/서브패키지는
통째로 제거한다 — main.py의 include_router 한 줄만 지우면 정리 끝난다.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import agent as rule_agent
from .embedding import embed_texts
from .vector_store import upsert_chunks

router = APIRouter(prefix="/agent/rule-v0", tags=["rule-agent-v0"])

# scope 허용값: GLOBAL 또는 settlements.Category 실제 값(정식 SoT — `domain/policies/models.py`
# RULE_SCOPE_CHOICES = [GLOBAL, *Category.choices]).
# [2026-08-14] "업무활성" Category가 실제로 폐지되고 "회식"이 독립 카테고리로 대체됐다(팀 확정 —
# 이전에 이 파일에 있던 같은 취지의 주장은 그 시점엔 사실이 아니었으나, 지금은 맞다). 회식 규정
# 그래프도 scope="식대"에서 scope="회식"으로 옮겨졌다(seed_rules.py `_seed_dining`).
Scope = Literal["GLOBAL", "회식", "회의", "식대", "출장", "접대", "비품"]


class RuleGenerateRequest(BaseModel):
    scope: Scope
    query: Optional[str] = None          # 미지정 시 scope별 기본 질의
    top_k: int = Field(default=6, ge=1, le=20)
    name: Optional[str] = None
    # family_key(기존 계열에 새 버전 추가)는 v0 범위 밖 — 항상 새 계열 v1로 생성.
    # v1: POST /api/rules/{id}/versions 오케스트레이션 추가 후 지원(GAPS.md 참조).


@router.post("/generate")
def generate_rules(req: RuleGenerateRequest):
    try:
        return rule_agent.generate(req)
    except Exception as exc:  # Chroma/OpenAI/Django 연결 실패를 배선 문제로 명확히 노출
        raise HTTPException(status_code=502, detail=f"rule generate 실패: {exc}")


# ---------------------------------------------------------------- 임베딩 적재
# 정식 스펙(§6.2)의 `/embeddings/upsert`와 별도로 v0 검증용 엔드포인트를 둔다.
# v1에서 정식 엔드포인트가 구현되면 이 라우트는 삭제하고 그쪽을 쓴다.


class ChunkIn(BaseModel):
    chunk_id: str                      # {doc_id}#{block_key}#{seq}
    embedding_text: str                # Chunk.embedding_text() 결과
    context_text: str                  # Chunk.context_text() 결과 (저장 문서)
    metadata: dict[str, Any]           # to_chroma() 스칼라 메타


class UpsertRequest(BaseModel):
    chunks: list[ChunkIn]
    skip_toc_like: bool = True         # chunking-strategy §9: toc_like 인덱싱 제외는 정책 몫


class UpsertResponse(BaseModel):
    upserted: int
    skipped: int


@router.post("/embeddings/upsert", response_model=UpsertResponse)
def upsert(req: UpsertRequest) -> UpsertResponse:
    kept, skipped = [], 0
    for c in req.chunks:
        flags = str(c.metadata.get("flags", ""))
        if req.skip_toc_like and "toc_like" in flags:
            skipped += 1
            continue
        kept.append(c)

    if not kept:
        return UpsertResponse(upserted=0, skipped=skipped)

    embeddings = embed_texts([c.embedding_text for c in kept])
    n = upsert_chunks(
        ids=[c.chunk_id for c in kept],
        documents=[c.context_text for c in kept],
        embeddings=embeddings,
        metadatas=[c.metadata for c in kept],
    )
    return UpsertResponse(upserted=n, skipped=skipped)
