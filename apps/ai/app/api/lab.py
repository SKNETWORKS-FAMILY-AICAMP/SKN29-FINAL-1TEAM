"""AI-LAB — AI 기능 독립 실행 API (`/lab/*`).

관리자가 **정산 흐름을 타지 않고** AI 기능만 따로 돌려보는 실험 통로다. 운영 경로(`/agent/*`,
`/embeddings/*`)와 **같은 코드를 부르되**, 결과만이 아니라 "왜 그렇게 나왔는지"(모델·프롬프트·
원본 응답·토큰·지연·정책 출처)를 함께 돌려준다. 별도 구현을 두지 않는 이유는 명확하다 —
실험 결과가 운영과 달라지는 순간 실험이 의미를 잃는다.

노출 경로: 브라우저 → Django `/api/ai-lab/*`(Capability `ai_lab` 인가) → 여기.
FastAPI는 내부 전용이라 사용자 트래픽을 직접 받지 않는다(CLAUDE.md §1).

기능이 추가되면 이 파일에 `/lab/<기능>/...`을 더하고 프론트 `screens/ai-lab/`에 탭을 하나 얹는다.
"""
from __future__ import annotations

import dataclasses
import time
from typing import Any, Literal, Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field, ValidationError

from app.agents import draft_agent
from app.clients import core_client
from app.config import settings
from app.ml.registry import get_active_model
from app.rag import chroma_client
from app.rag.embedding import config as emb_config
from app.rag.embedding import store
from app.rag.embedding.encoder import OpenAIEncoder

router = APIRouter()


# ── 공통 ────────────────────────────────────────────────────────────────

def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _config_for(use_query_prefix: bool) -> emb_config.EmbeddingConfig:
    """질의 접두(`Q_ctx`) on/off — 임베딩 전략 §7의 비대칭 입력을 실측으로 재현해 보기 위한 스위치.

    차원·모델은 바꾸지 않는다. 적재된 벡터와 차원이 어긋나면 검색이 실패할 뿐 실험이 되지 않는다.
    """
    if use_query_prefix:
        return emb_config.DEFAULT
    return dataclasses.replace(emb_config.DEFAULT, query_prefix="")


def _fail(status: int, message: str, exc: Exception | None = None) -> HTTPException:
    """실패를 조용히 삼키지 않는다 — 화면이 그대로 보여줄 수 있는 문장으로 올린다."""
    detail = f"{message}: {type(exc).__name__}: {exc}" if exc else message
    return HTTPException(status_code=status, detail=detail)


# ── 상태 점검 ───────────────────────────────────────────────────────────

@router.get("/status")
def status() -> dict:
    """실험 전에 "지금 무엇이 준비되어 있는지"를 한 번에 본다.

    OpenAI 키·Chroma 적재량·Django 연결·이상탐지 모델 — 하나라도 비면 어떤 탭이 왜 안 도는지가
    화면에서 바로 설명된다(실행해 보고 500을 받는 것보다 낫다).
    """
    started = time.perf_counter()
    chroma_ok = chroma_client.heartbeat()

    collections: list[dict[str, Any]] = []
    for name in emb_config.ALL_COLLECTIONS:
        row: dict[str, Any] = {"name": name, "count": 0, "embedderVersions": {}, "error": None}
        if chroma_ok:
            try:
                info = store.peek(name)
                row.update(count=info["count"], embedderVersions=info["embedder_versions"])
            except Exception as exc:  # noqa: BLE001
                row["error"] = f"{type(exc).__name__}: {exc}"
        collections.append(row)

    core_ok, core_error = True, None
    try:
        core_client.health()
    except Exception as exc:  # noqa: BLE001
        core_ok, core_error = False, f"{type(exc).__name__}: {exc}"

    model = get_active_model()
    cfg = emb_config.DEFAULT
    return {
        "service": "ai",
        "latencyMs": _elapsed_ms(started),
        "openai": {
            "configured": bool(settings.openai_api_key),
            "draftModel": draft_agent.MODEL,
            "embeddingModel": cfg.model,
            "dimensions": cfg.dimensions,
            "queryPrefix": cfg.query_prefix,
            "embedderVersion": cfg.version,
        },
        "chroma": {
            "reachable": chroma_ok,
            "endpoint": settings.chroma_persist_dir or chroma_client.base_url(),
            "collections": collections,
        },
        "core": {"reachable": core_ok, "baseUrl": settings.core_base_url, "error": core_error},
        "anomalyModel": {"loaded": bool(model), "fitted": bool(model and model.fitted)},
    }


# ── ① Draft Agent ───────────────────────────────────────────────────────

@router.post("/draft/run")
def draft_run(payload: dict = Body(...)) -> dict:
    """운영과 같은 분기(`instruction` 유무 = 수정/생성)로 Draft Agent를 실행하고 추적을 함께 반환.

    요청 검증 실패는 422로 올린다 — 화면이 어떤 필드가 왜 틀렸는지 그대로 보여줄 수 있게.
    """
    from app.api.draft import DraftRequest, ReviseRequest      # 순환 import 회피(런타임 지연 import)

    trace: dict[str, Any] = {"fallbackUsed": False}
    started = time.perf_counter()

    if str(payload.get("instruction", "")).strip():
        try:
            req = ReviseRequest(**payload)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
        result = draft_agent.revise(req, trace)
    else:
        try:
            req = DraftRequest(**payload)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
        result = draft_agent.run(req, trace)

    trace["totalMs"] = _elapsed_ms(started)
    return {"request": payload, "result": result, "trace": trace}


# ── ② RAG ───────────────────────────────────────────────────────────────

class RagSearchRequest(BaseModel):
    query: str
    collection: str = "policy_docs"
    topK: int = Field(default=5, ge=1, le=50)
    expandParent: bool = True
    useQueryPrefix: bool = True


@router.post("/rag/search")
def rag_search(req: RagSearchRequest) -> dict:
    """규정 청크 검색 — 운영 검색(`store.search`)을 그대로 부른다.

    점수·인용·메타데이터·부모 확장까지 전부 돌려주므로, "이 질의에 왜 이 조문이 걸렸는지"를
    화면에서 조문 단위로 확인할 수 있다.
    """
    if not settings.openai_api_key:
        raise _fail(400, "OPENAI_API_KEY가 비어 있어 질의를 임베딩할 수 없습니다(레포 루트 .env 확인)")
    if req.collection not in emb_config.ALL_COLLECTIONS:
        raise _fail(400, f"알 수 없는 컬렉션: {req.collection} (가능: {', '.join(emb_config.ALL_COLLECTIONS)})")

    cfg = _config_for(req.useQueryPrefix)
    started = time.perf_counter()
    try:
        hits = store.search(
            req.query,
            collection_name=req.collection,
            top_k=req.topK,
            config=cfg,
            expand_parent=req.expandParent,
        )
    except Exception as exc:  # noqa: BLE001
        raise _fail(502, "검색 실패 — Chroma 연결·적재 상태를 확인하세요", exc) from exc

    return {
        "query": req.query,
        "collection": req.collection,
        "embedderVersion": cfg.version,
        "queryPrefix": cfg.query_prefix,
        "latencyMs": _elapsed_ms(started),
        "hits": hits,
        "judgementCollection": req.collection in emb_config.JUDGEMENT_COLLECTIONS,
    }


class RagEmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=16)
    # query = 질의 접두(`Q_ctx`)를 붙여서, raw = 원문 그대로. 문서 쪽 계층 헤더 주입은 청킹의 몫이라
    # 임의 텍스트에는 붙일 것이 없다 — 있지도 않은 'document 모드'를 흉내 내지 않는다.
    mode: Literal["query", "raw"] = "query"


@router.post("/rag/embed")
def rag_embed(req: RagEmbedRequest) -> dict:
    """텍스트 → 벡터. 질의 접두가 벡터를 실제로 얼마나 움직이는지 눈으로 보는 칸.

    벡터는 L2 정규화되어 있으므로 cosine = 내적이다 — 유사도 행렬을 그대로 곱해서 만든다.
    """
    if not settings.openai_api_key:
        raise _fail(400, "OPENAI_API_KEY가 비어 있어 임베딩을 호출할 수 없습니다")

    cfg = emb_config.DEFAULT
    encoder = OpenAIEncoder(cfg)
    started = time.perf_counter()
    try:
        if req.mode == "query":
            vectors = encoder.encode_queries(req.texts)
        else:
            vectors = encoder.encode_texts(req.texts)
    except Exception as exc:  # noqa: BLE001
        raise _fail(502, "임베딩 호출 실패", exc) from exc

    similarity = [[round(sum(a * b for a, b in zip(u, v)), 4) for v in vectors] for u in vectors]
    return {
        "mode": req.mode,
        "model": cfg.model,
        "dimensions": cfg.dimensions,
        "embedderVersion": cfg.version,
        "appliedPrefix": cfg.query_prefix if req.mode == "query" else "",
        "billedTokens": encoder.billed_tokens,
        "latencyMs": _elapsed_ms(started),
        "vectors": [
            {"text": text, "dim": len(vec), "head": [round(x, 5) for x in vec[:8]]}
            for text, vec in zip(req.texts, vectors)
        ],
        "similarity": similarity,
    }


@router.get("/rag/collections")
def rag_collections() -> dict:
    """적재 현황 — 컬렉션별 건수와 임베딩 신원(섞였는지 여부 포함)."""
    rows = []
    for name in emb_config.ALL_COLLECTIONS:
        try:
            info = store.peek(name)
            rows.append({
                "name": name,
                "count": info["count"],
                "embedderVersions": info["embedder_versions"],
                "mixedEmbedder": len(info["embedder_versions"]) > 1,
                "judgement": name in emb_config.JUDGEMENT_COLLECTIONS,
                "error": None,
            })
        except Exception as exc:  # noqa: BLE001
            rows.append({"name": name, "count": 0, "embedderVersions": {}, "mixedEmbedder": False,
                         "judgement": name in emb_config.JUDGEMENT_COLLECTIONS,
                         "error": f"{type(exc).__name__}: {exc}"})
    return {"collections": rows}


@router.get("/rag/collections/{name}/sample")
def rag_sample(name: str, limit: int = 10, docName: Optional[str] = None) -> dict:
    """적재된 청크를 직접 들여다본다 — 검색이 이상할 때 "무엇이 들어가 있는지"부터 본다."""
    if name not in emb_config.ALL_COLLECTIONS:
        raise _fail(400, f"알 수 없는 컬렉션: {name}")
    limit = max(1, min(limit, 50))
    try:
        collection = store.get_collection(store.get_client(), name)
        got = collection.get(
            limit=limit,
            where={"doc_name": docName} if docName else None,
            include=["documents", "metadatas"],
        )
    except Exception as exc:  # noqa: BLE001
        raise _fail(502, "샘플 조회 실패 — Chroma 연결 상태를 확인하세요", exc) from exc

    items = [
        {"chunkId": cid, "document": doc, "metadata": meta}
        for cid, doc, meta in zip(got.get("ids", []), got.get("documents", []), got.get("metadatas", []))
    ]
    return {"collection": name, "count": len(items), "items": items}
