# apps/core/domain/policies/rule_agent_v0_views.py
"""룰 작성 카탈로그 payload — 룰 콘솔 화면(`RuleGraphViewSet.action_schema`)이 쓰는 조각.

에이전트용 카탈로그 조회는 `domain/context`(`/api/internal/agent-context/`)로 옮겼다.
여기 있던 `EvalContextSchemaView`/`ActionSchemaView`는 그 엔드포인트의 부분집합이라
제거했다 — 같은 값을 주는 창구가 둘이면 하나는 반드시 뒤처진다.

남은 `action_schema_payload()`는 **브라우저** 경로다. 룰 콘솔은 인가(`rule_view`)를
지나야 하므로 AllowAny 내부 API를 쓸 수 없고, ai가 쓰는 카탈로그와 소스(`engine.py`)만
공유하면 된다.
"""
from __future__ import annotations

from .engine import DECISIONS_CATALOG, PASS_THROUGH, SEVERITIES_CATALOG


def action_schema_payload() -> dict:
    return {
        "decisions": list(DECISIONS_CATALOG),
        "severities": list(SEVERITIES_CATALOG),
        "passThrough": PASS_THROUGH,
    }
