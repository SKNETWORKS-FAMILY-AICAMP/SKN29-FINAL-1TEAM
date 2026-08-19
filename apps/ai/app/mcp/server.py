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
    # 가맹점 업종 재분류 — 카카오 원시 카테고리를 우리 서비스 어휘로 (fix/risk-review 계열)
    tools.classify_merchant,
    # 비전 판독 2종 — 영수증(사용내역+사실) / 증빙 문서(사실만)
    tools.read_receipt,
    tools.read_evidence_document,
    tools.search_policy,
    tools.search_cases,
    tools.fetch_historical_tx,
    tools.build_rule_context,
    tools.run_rule_engine,
    tools.get_tx_features,
    tools.ml_infer,
):
    # fastmcp 2.x의 FastMCP.tool()은 데코레이터 팩토리라 `()`로 먼저 호출해야 한다.
    # `mcp.tool(_fn)`은 _fn을 `name` 위치인자로 넘기는 꼴이라 조용히 실패하고,
    # main.py의 마운트 가드가 예외를 삼켜서 `/mcp` 전체가 안 뜨는데도 앱은 부팅됐다
    # (실측 2026-08-16: `FastMCP mount skipped` 경고로만 남아 있었음).
    mcp.tool()(_fn)
