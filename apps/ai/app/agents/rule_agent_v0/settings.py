# apps/ai/app/agents/rule_agent_v0/settings.py
"""v0 전용 설정. 중앙 `app/config.py`의 Settings 클래스를 건드리지 않기 위해
환경변수를 직접 읽는다 — v0를 통째로 들어내도 config.py는 원상태 그대로다.

OPENAI_API_KEY는 중앙 config.py가 이미 로드하는 값과 동일한 env var를 재사용한다
(중복 정의 아님, 같은 .env 키를 읽을 뿐).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RuleAgentV0Settings:
    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
    chroma_host: str = os.environ.get("RULE_AGENT_V0_CHROMA_HOST", "")
    chroma_port: int = int(os.environ.get("RULE_AGENT_V0_CHROMA_PORT", "8001"))
    chroma_path: str = os.environ.get("RULE_AGENT_V0_CHROMA_PATH", "./chroma_data_v0")
    django_internal_base: str = os.environ.get(
        "RULE_AGENT_V0_DJANGO_BASE", "http://core:8000"
    )
    # G-16 인증 블로커 — 값이 비어 있으면 헤더 없이 호출(현재 create_rule_graph_draft는
    # 401/403 예상). 서비스 인증 방식이 정해지면 여기 채우면 된다.
    django_service_token: str = os.environ.get("RULE_AGENT_V0_DJANGO_SERVICE_TOKEN", "")
    model: str = os.environ.get("RULE_AGENT_V0_MODEL", "gpt-4o-mini")


settings = RuleAgentV0Settings()