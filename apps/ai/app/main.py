"""AI Orchestrator (FastAPI) 진입점 (기술명세서 §4, §6.2).

- Draft / Rule / Risk Review Agent 오케스트레이션
- 단일 FastMCP 서버(/mcp)로 표준 도구 노출
- 내부 전용(동기 REST). 사용자 트래픽은 Django만 받는다.
"""
import logging

from fastapi import FastAPI

from app import logging_setup

# 라우터 import보다 **먼저** 로깅을 켠다 — 그래야 import 시점 경고(모델 로드 실패 등)도 파일에 남는다.
_log_file = logging_setup.setup()

from app.api import draft, embeddings, health, ml, risk, rule, lab  # noqa: E402
from app.agents.rule_agent_v0 import router as rule_agent_v0_router  # noqa: E402

logging.getLogger(__name__).info(
    "AI Orchestrator 기동 — 로그 파일: %s", _log_file or "(콘솔만)"
)

app = FastAPI(title="Settlement AI Orchestrator", version="0.1.0")

# 라우터
app.include_router(health.router)
app.include_router(draft.router, prefix="/agent", tags=["agent"])
app.include_router(rule.router, prefix="/agent", tags=["agent"])
app.include_router(risk.router, prefix="/agent", tags=["agent"])
app.include_router(ml.router, prefix="/ml", tags=["ml"])
app.include_router(embeddings.router, prefix="/embeddings", tags=["rag"])

app.include_router(rule_agent_v0_router)   # ← 추가 (prefix 없이 — 라우터 자체에 /agent/rule-v0 내장돼 있음)

# AI-LAB: 관리자 실험 화면 전용. Django `/api/ai-lab/*` 프록시(Capability `ai_lab`)로만 노출된다.
app.include_router(lab.router, prefix="/lab", tags=["lab"])

# 단일 FastMCP 서버 마운트 — import/버전 이슈가 있어도 앱은 항상 부팅되도록 guard.
try:
    from app.mcp.server import mcp

    # 설치된 fastmcp==2.1.2에는 `http_app()`(Streamable HTTP, 이후 버전에 추가)이 없다 —
    # 이 버전에서 ASGI 앱을 얻는 방법은 `sse_app()`(SSE 트랜스포트)뿐이다. 참고: Rule Agent
    # 등 같은 프로세스 안에서 도구를 부르는 내부 호출자는 이 HTTP 마운트를 거치지 않고
    # `fastmcp.Client(mcp)`(in-process 트랜스포트)로 직접 붙는다 — 이 마운트는 외부
    # MCP 클라이언트(예: Claude Desktop)를 위한 것.
    app.mount("/mcp", mcp.sse_app())
except Exception as exc:  # noqa: BLE001  # pragma: no cover
    logging.getLogger("uvicorn.error").warning("FastMCP mount skipped: %s", exc)
