"""규정 문서 적재 엔드포인트 (관리자 트리거, 기술명세서 §6.2).

    core: 업로드 수신 ─► POST /embeddings/ingest ─(즉시 202)─► 백그라운드
                                                                 파싱→청킹→임베딩→적재
                                                                 → 룰 트리거(현재 개발 중)
                                                                 → core 콜백으로 결과 회신

**즉시 반환하는 이유**: docling 파싱은 모델을 올리고 문서당 수십 초~분이 걸린다. 요청 안에서
끝내려 하면 브라우저(그리고 그 앞의 nginx)가 먼저 끊는다.

**큐를 쓰지 않는 이유**: 실제 부하는 관리자가 가끔 규정 몇 종을 올리는 것이다. 브로커·워커
컨테이너를 새로 들이는 비용이 그 부하에 비해 크고, 기술명세서 §6.2의 "동기 REST · 별도 Job
큐 없음" 결정과도 어긋난다. 대신 진행 상태를 core의 `PolicyDoc.status`에 두어 화면이
언제든 실제 상태를 볼 수 있게 했다.

**한계(알고 쓰는 것)**: `BackgroundTasks`는 이 프로세스 안에서 돈다. uvicorn이 재시작되면
(dev는 `--reload`라 파일 저장만 해도) 진행 중이던 적재는 사라지고 문서는 `PARSING`/`INDEXING`에
멈춘다. 복구는 사람이 "재색인"을 누르는 것이고, 그건 관리자 온디맨드 배치라는 전제와
일관된 회복 경로다. 규모가 커지면 이 자리에 큐를 끼우면 된다 — 호출 계약은 그대로 둘 수 있다.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field

from app.clients import core_auth
from app.rag import ingest as ingest_mod
from app.rag import rule_trigger
from app.rag.embedding import config as emb_config
from app.rag.embedding import store

logger = logging.getLogger(__name__)
router = APIRouter()

# core와 같은 media 볼륨을 읽기전용으로 마운트한 위치(compose). docling이 파일 경로를
# 요구하므로 바이트를 HTTP로 되넘기는 대신 볼륨을 공유한다.
MEDIA_ROOT = Path(os.environ.get("RAG_MEDIA_ROOT", "/data/media"))

# core `PolicyDoc.IngestStatus`와 같은 값이어야 한다 — 콜백이 그대로 상태로 쓰인다.
PARSING, INDEXING, DONE, FAILED = "PARSING", "INDEXING", "DONE", "FAILED"


class IngestRequest(BaseModel):
    policyDocId: int
    filePath: str = Field(description="media 볼륨 기준 상대경로 (`PolicyDoc.file.name`)")
    name: str | None = None
    ruleScope: str = ""


def _report(doc_id: int, payload: dict) -> None:
    """적재 결과를 core에 회신한다. 실패해도 예외를 올리지 않는다 —
    백그라운드 태스크에서 터지면 아무도 못 보고, 문서만 진행 중에 멈춘다."""
    try:
        core_auth.request(
            "POST", f"/api/internal/policy-docs/{doc_id}/ingest-result/", json=payload, timeout=30.0
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("적재 결과 회신 실패 doc=%s: %s", doc_id, exc)


def _run(req: IngestRequest) -> None:
    """백그라운드 본체 — 파싱·청킹·적재 → 룰 트리거 → 회신."""
    _report(req.policyDocId, {"status": PARSING})

    path = MEDIA_ROOT / req.filePath
    result = ingest_mod.ingest_pdf(path, name=req.name)
    if not result.ok:
        _report(req.policyDocId, {
            "status": FAILED, "error": result.error, "docId": result.doc_id,
            "profile": result.profile,
        })
        return

    # 적재가 끝난 **뒤에만** 룰을 트리거한다 — 그 전이면 검색이 0건이라 NO_SOURCE로 끝난다.
    # 실패해도 적재를 실패로 만들지 않는다: 문서는 이미 검색 가능하고, 룰은 수동 생성이 된다.
    try:
        trigger = rule_trigger.trigger(
            doc_id=result.doc_id, doc_name=result.name,
            scope=req.ruleScope, collection=result.collection,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("룰 트리거 실패 doc=%s: %s", req.policyDocId, exc)
        trigger = {"status": "ERROR", "detail": f"{type(exc).__name__}: {exc}"}

    _report(req.policyDocId, {
        "status": DONE,
        "docId": result.doc_id,
        "profile": result.profile,
        "collection": result.collection,
        "chunkCount": result.chunk_count,
        "leafCount": result.leaf_count,
        "error": "\n".join(result.warnings[:5]),   # 경고는 실패가 아니지만 보여야 한다
        "ruleTrigger": trigger,
    })


@router.post("/ingest", status_code=202)
def ingest(req: IngestRequest, background: BackgroundTasks):
    """적재 **요청 접수**. 실제 작업은 백그라운드에서 돌고 결과는 core로 회신된다."""
    background.add_task(_run, req)
    return {"accepted": True, "policyDocId": req.policyDocId, "status": PARSING}


@router.get("/collections")
def collections():
    """적재 현황 — 컬렉션별 건수와 임베딩 신원. 인덱싱이 실제로 됐는지 확인용."""
    out = []
    for name in emb_config.ALL_COLLECTIONS:
        try:
            info = store.peek(name)
        except Exception as exc:  # noqa: BLE001  # Chroma 미기동 등 — 감추지 않는다
            out.append({"collection": name, "error": f"{type(exc).__name__}: {exc}"})
            continue
        out.append({**info, "judgement": name in emb_config.JUDGEMENT_COLLECTIONS})
    return {"collections": out}
