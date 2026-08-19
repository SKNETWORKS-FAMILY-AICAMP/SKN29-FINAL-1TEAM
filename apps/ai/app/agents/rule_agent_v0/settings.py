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
    # 경량 모델 — 판정/생성 결과에 영향 없는 표시용 변환(예: 검증셋 라벨·가맹점명 문구화)에만 쓴다.
    model: str = os.environ.get("RULE_AGENT_MODEL", "gpt-4o-mini")
    # 심층 모델 — 실제 산출물을 만들거나 깊은 판단이 들어가는 호출(룰 그래프 생성·대화형 수정·
    # 시뮬레이션 보고서 서술)에 쓴다. 2026-08-18 전수조사로 도입 — 그 전엔 4개 호출 전부가
    # `model` 하나를 공유해 표시용 문구화까지 판단이 중요한 호출과 같은 모델을 쓰고 있었다.
    model_heavy: str = os.environ.get("RULE_AGENT_MODEL_HEAVY", "gpt-5-mini")
    # gpt-5-mini 기본(medium) 추론 노력은 실측 40초대 — 대부분 다중 섹션 마크다운을 길게
    # 뽑느라 걸리는 시간이라 reasoning_effort를 낮춰도 품질 저하가 뚜렷하지 않았다(실측:
    # minimal/low 둘 다 ~23초, medium 41초). 'low'를 기본으로 — 'minimal'보다 살짝 더 깊게
    # 생각하되 medium의 지연은 피한다.
    model_heavy_reasoning_effort: str = os.environ.get("RULE_AGENT_MODEL_HEAVY_REASONING_EFFORT", "low")
    # 서비스 계정(최소 권한: rule_view 하나). 비밀번호가 비면 인증 없이 호출해 403이 난다 —
    # 조용히 익명으로 떨어지지 않도록 django_client가 그 사실을 사유에 명시한다.
    service_user: str = os.environ.get("RULE_AGENT_SERVICE_USER", "rule-agent")
    service_password: str = os.environ.get("RULE_AGENT_SERVICE_PASSWORD", "")


settings = RuleAgentSettings()
