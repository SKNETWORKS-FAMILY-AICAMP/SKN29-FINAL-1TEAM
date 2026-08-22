"""프로파일 — 에이전트별 섹션 묶음.

섹션을 호출부가 매번 고르게 두면 에이전트마다 목록이 또 갈린다(그게 지금 고치는
문제다). 묶음에 이름을 붙여 **"이 에이전트는 이만큼을 안다"** 를 한 곳에서 정한다.

프로파일을 늘릴 때의 기준: 프롬프트에 실을 여유가 있어서가 아니라, **그 에이전트가
그 어휘로 무언가를 쓰거나 판정하기 때문에** 넣는다. 안 쓰는 카탈로그는 토큰만 먹고
모델의 주의를 흩뜨린다.
"""
from __future__ import annotations

#: P0 — 룰 생성·대화. P1에서 vocab.* / graph.current / risk_stage2가 붙는다.
PROFILES: dict[str, tuple[str, ...]] = {
    # 규정 문서 → 룰 그래프 DRAFT 생성 (`rule_agent_v0/agent.py`)
    "rule_generate": (
        "dsl.grammar",
        "eval_context.paths",
        "policy.vars",
        "action.schema",
        "flags.registry",
    ),
    # 룰 콘솔 대화형 수정 (`rule_agent_v0/chat.py`) — 같은 어휘로 고쳐야 생성물과 어긋나지 않는다.
    "rule_chat": (
        "dsl.grammar",
        "eval_context.paths",
        "policy.vars",
        "action.schema",
        "flags.registry",
    ),
}


def sections_for(profile: str) -> tuple[str, ...]:
    if profile not in PROFILES:
        raise KeyError(profile)
    return PROFILES[profile]
