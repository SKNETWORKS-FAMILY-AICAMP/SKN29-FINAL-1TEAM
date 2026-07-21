"""AI Orchestrator (FastAPI) 진입점 (기술명세서 §4, §6.2).

- Draft / Rule / Risk Review Agent 오케스트레이션
- 단일 FastMCP 서버(/mcp)로 표준 도구 노출
- 내부 전용(동기 REST). 사용자 트래픽은 Django만 받는다.
"""
import logging

from fastapi import FastAPI

from app.api import draft, embeddings, health, ml, risk, rule

app = FastAPI(title="Settlement AI Orchestrator", version="0.1.0")

# 라우터
app.include_router(health.router)
app.include_router(draft.router, prefix="/agent", tags=["agent"])
app.include_router(rule.router, prefix="/agent", tags=["agent"])
app.include_router(risk.router, prefix="/agent", tags=["agent"])
app.include_router(ml.router, prefix="/ml", tags=["ml"])
app.include_router(embeddings.router, prefix="/embeddings", tags=["rag"])

# 단일 FastMCP 서버 마운트 — import/버전 이슈가 있어도 앱은 항상 부팅되도록 guard.
try:
    from app.mcp.server import mcp

    app.mount("/mcp", mcp.http_app())
except Exception as exc:  # noqa: BLE001  # pragma: no cover
    logging.getLogger("uvicorn.error").warning("FastMCP mount skipped: %s", exc)
