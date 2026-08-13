# apps/ai/app/agents/rule_agent_v0/__init__.py
"""Rule Agent v0 — 자기완결 서브패키지.

main.py에서 필요한 건 이거 하나뿐이다:

    from app.agents.rule_agent_v0 import router as rule_agent_v0_router
    app.include_router(rule_agent_v0_router)

"""
from .api import router

__all__ = ["router"]
