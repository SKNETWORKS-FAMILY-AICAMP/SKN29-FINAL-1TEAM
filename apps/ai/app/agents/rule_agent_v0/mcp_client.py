# apps/ai/app/agents/rule_agent_v0/mcp_client.py
"""Rule Agent가 MCP 서버(`app.mcp.server.mcp`)를 부르는 통로.

같은 프로세스 안이라 HTTP(`/mcp` 마운트)를 거치지 않는다 — `fastmcp.Client`가 `FastMCP`
인스턴스를 직접 받으면 in-process 트랜스포트로 붙는다(네트워크 왕복 없음). `/mcp` HTTP
마운트는 Claude Desktop 같은 **외부** MCP 클라이언트를 위한 것이고, 이 파일은 그거와
무관하게 동작한다.

`fastmcp.Client`는 비동기 전용이다. `generate()`는 동기 함수라(Django/httpx 호출이
전부 동기) 매 호출마다 `asyncio.run()`으로 짧게 이벤트 루프를 띄운다 — FastAPI의 동기
라우트 핸들러는 스레드풀에서 돌아 이미 실행 중인 루프가 없으므로 안전하다.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastmcp import Client

from app.mcp.server import mcp as _mcp_server


def call_tool(name: str, **kwargs: Any) -> dict[str, Any]:
    """MCP 툴 1회 호출. 툴 반환값(dict)이 JSON 텍스트로 오므로 파싱해서 돌려준다."""

    async def _call() -> dict[str, Any]:
        async with Client(_mcp_server) as client:
            result = await client.call_tool(name, kwargs)
            return json.loads(result[0].text)

    return asyncio.run(_call())
