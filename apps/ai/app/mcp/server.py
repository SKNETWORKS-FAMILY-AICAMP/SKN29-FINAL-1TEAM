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
    tools.run_rule_engine,
    tools.get_tx_features,
    tools.ml_infer,
):
    mcp.tool(_fn)
