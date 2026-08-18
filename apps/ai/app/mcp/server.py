"""단일 FastMCP 서버 (기술명세서 §5).

3개 Agent(Draft/Rule/Risk)가 공유하는 표준 도구를 모두 노출한다.
Agent별 서버 분리 없이 단일 서버로 단순화(MVP).
"""
from fastmcp import FastMCP

from app.mcp import tools

mcp = FastMCP("settlement-tools")

for _fn in (
    tools.get_policy,
    tools.get_card_context,
    tools.search_policy,
    tools.search_cases,
    tools.fetch_historical_tx,
    tools.build_rule_context,
    tools.run_rule_engine,
    tools.get_tx_features,
    tools.ml_infer,
):
    # `mcp.tool()`은 데코레이터 팩토리라 함수를 직접 넘기면(`mcp.tool(_fn)`) `_fn`이
    # `name` 인자로 잘못 들어가 아무 것도 등록되지 않는다(FastMCP가 이 오용을 감지해
    # "Use @tool() instead of @tool" TypeError를 던진다 — main.py의 try/except가
    # 이를 삼켜 "FastMCP mount skipped" 경고로만 보이고, /mcp 전체가 마운트되지 않는다).
    # 미리 만든 함수를 등록하는 정식 API는 `add_tool`이다.
    mcp.add_tool(_fn)
