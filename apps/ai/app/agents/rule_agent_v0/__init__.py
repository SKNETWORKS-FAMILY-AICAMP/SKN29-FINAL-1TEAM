# apps/ai/app/agents/rule_agent_v0/__init__.py
"""Rule Agent — 생성(Generate). 규정 문서(RAG) → 룰 그래프 DRAFT.

설계 결정·남은 갭·실행 방법은 `llm_wiki/_context/rule-agent-v0.md`가 정본이다.

main.py에서 필요한 건 이거 하나뿐이다:

    from app.agents.rule_agent_v0 import router as rule_agent_v0_router
    app.include_router(rule_agent_v0_router)

`_v0` 접미사는 정식 엔드포인트(`/agent/rule/generate`, 기술명세서 §6.2)로 이관하기 전의
과도기 이름이었다 — 그 정식 경로를 잡고 있던 `api/rule.py`(전부 stub, 아무도 안 부름)를
2026-08-21 전수 점검에서 삭제했다. 이관 없이 `rule-v0`가 그대로 정식 경로 역할을 한다.
"""
from .api import router

__all__ = ["router"]
