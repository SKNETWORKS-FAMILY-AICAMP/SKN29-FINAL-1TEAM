# apps/ai/app/agents/rule_agent_v0/settings.py
"""Rule Agent 전용 설정 — 중앙 `app/config.py`에 없는 값만 둔다.

**여기서 Chroma·OpenAI·Django 주소를 다시 정의하지 않는다.** 그건 중앙
`app.config.settings`(compose가 `CHROMA_HOST`/`CORE_BASE_URL`/`OPENAI_API_KEY`로 주입)가
갖고 있고, 사본을 두면 컨테이너에서만 조용히 어긋난다 — 실제로 그랬다. v0의
`RULE_AGENT_V0_CHROMA_HOST`는 기본값이 빈 문자열이라 docker에서 로컬 빈 DB로
폴백했고, 검색이 0건이 나도 에러 없이 `NO_SOURCE`만 돌려줬다.

남는 건 이 Agent에만 있는 두 가지뿐이다:
  - LLM 모델(다른 Agent와 따로 바꿔 끼울 수 있어야 함)
  - Django 서비스 계정 자격증명 — Rule Agent는 사람 세션 없이 룰 콘솔 API에
    쓰기를 해야 하므로 `rule_view` capability만 가진 전용 계정으로 JWT를 받는다
    (`django_client._access_token`). 계정 생성은 `manage.py ensure_service_account`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RuleAgentSettings:
    model: str = os.environ.get("RULE_AGENT_MODEL", "gpt-4o-mini")
    # 서비스 계정(최소 권한: rule_view 하나). 비밀번호가 비면 인증 없이 호출해 403이 난다 —
    # 조용히 익명으로 떨어지지 않도록 django_client가 그 사실을 사유에 명시한다.
    service_user: str = os.environ.get("RULE_AGENT_SERVICE_USER", "rule-agent")
    service_password: str = os.environ.get("RULE_AGENT_SERVICE_PASSWORD", "")


settings = RuleAgentSettings()
