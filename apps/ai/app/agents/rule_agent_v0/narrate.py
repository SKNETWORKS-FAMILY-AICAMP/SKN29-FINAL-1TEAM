# apps/ai/app/agents/rule_agent_v0/narrate.py
"""Rule Agent — 시뮬레이션 보고서 서술 생성 + 권장 처리 판단.

`apps/core/domain/policies/simulation.py::_render_template_report()`가 원래 담당하던
"통계·판정을 사람이 읽을 마크다운으로 편성"하는 일 중 **서술문 작성**을 LLM에 맡긴다.
판정·통계·구조/실행결과 평가(structure/result 등급) 자체는 Django가 룰 엔진으로 이미
확정한 값이고(`facts` 인자), 여기서는 그 값을 재계산하지 않는다.

2026-08-19부터 **"권장 처리"(action) 등급만은 LLM이 조금 관여**한다 — 이전엔 `_grades()`가
"구조/실행결과 중 더 나쁜 쪽을 그대로 채택"하는 단순 규칙(AND 게이트)이었는데, 사용자가
"LLM이 조금 들어가서 판단해도 될 것 같다"고 요청했다. 다만 안전 하한은 유지한다 —
**구조 평가가 '미흡'(구조 오류·도달불가 노드)이면 LLM도 '수정'을 벗어난 등급을 줄 수
없다**(그래프가 구조적으로 깨진 상태를 LLM 판단으로 "활성화해도 된다"고 뒤집으면 안
된다). 이 하한은 프롬프트 지시로만 걸지 않고 Django `apply_action_assessment()`에서
서버 측으로 한 번 더 강제 검증한다(§ 구현 기록: `rule-agent-v1-ux-upgrade-plan.md`).

호출부(`views.py` RuleGraphViewSet.simulate)는 이 함수가 실패해도 시뮬레이션 자체를
실패시키지 않는다 — Django `simulation.py`의 결정론적 템플릿(`_render_template_report`)과
결정론적 action 등급이 항상 폴백으로 남아 있다(§13.3, `rule-agent-v1-implementation.md`).
"""
from __future__ import annotations

import json
from typing import Any

from .agent import _openai
from .settings import settings

_SYSTEM_PROMPT = """당신은 법인카드 정산 룰 콘솔의 시뮬레이션 보고서를 작성하고, "권장 처리"를
판단하는 보조입니다. 회계 담당자가 이 룰 그래프를 활성화해도 되는지 판단하는 데 씁니다.

서술(report) 작성 원칙:
1. 입력으로 주어진 JSON(facts)에 있는 사실만 사용하세요 — 숫자·건수·판정 결과를 지어내거나
   반올림 이상으로 바꾸지 마세요. facts에 없는 내용은 쓰지 마세요.
2. **반드시 `## 한눈에 보기`로 시작하세요.** 회계 담당자가 이 섹션만 읽어도 판단할 수
   있도록 최대 3~4줄로 압축: ①권장 처리 결론(활성화해도 되는지) ②가장 중요한 이유
   1~2개 ③가장 먼저 확인해야 할 것 1개. 여기서는 통계를 나열하지 말고 결론과 핵심
   근거만 — 나머지 디테일은 뒤 섹션에서 다룹니다.
3. `## 한눈에 보기` 다음에 헤딩(##)으로 섹션을 나눠 다음 내용을 반드시 포함하세요:
   개요(무엇을 시뮬레이션했는지 + 판단 근거 + 권장 처리), 그래프 구성 평가, 실행결과
   (테스트케이스 결과 · 실제 내역 결과 · 노드 커버리지), 주의깊게 살펴봐야 할 부분. 이
   섹션들은 화면에서 기본적으로 접혀 있습니다 — 필요한 사람만 펼쳐 봅니다.
4. 딱딱한 통계 나열이 아니라, 담당자가 왜 이 결론에 이르렀는지 자연스러운 문장으로
   풀어 쓰세요. 다만 근거가 되는 구체적 수치(건수·비율)는 반드시 문장 안에 남기세요.
5. `watch`(주의사항)가 비어 있으면 "특별히 확인할 점이 없다"는 취지로 짧게 마무리하세요.
6. **숫자만 던지지 말고 "왜 그 숫자가 나왔는지"를 설명하세요.** `testExamples`/
   `riskyExamples`에 있는 구체적 사례를 최소 1개는 실행결과 섹션에 인용하세요 — 예:
   "예를 들어 `{label}` 건은 `{path}` 경로를 거쳐 `{decision}`으로 판정됐습니다"처럼
   실제 값을 채워 쓰세요. 두 배열이 비어 있으면 억지로 지어내지 말고 생략하세요.

권장 처리(action) 판단 원칙:
7. facts.grades에 Django가 이미 계산한 structure/result 등급(각 poor/warn/good)과 그
   기계적 결론(action)이 들어있습니다. 그 기계적 결론은 "둘 중 더 나쁜 쪽을 그대로
   채택"하는 단순 규칙이라, 구조는 사소한 경고(warn)인데 결과가 완벽하면 지나치게
   보수적일 수 있고, 반대로 결과가 조금 안 좋아도 맥락상 괜찮은 경우가 있습니다. 당신은
   `facts` 전체(구조·통계·위험변경 사례 등)를 종합해 poor/warn/good 중 **당신의 판단으로**
   action.level·note를 다시 정하세요.
8. **단, 절대적 하한이 있습니다: `facts.grades.structure.level`이 `poor`이면(구조 오류 또는
   도달 불가 노드) 당신도 action.level을 반드시 `poor`로 유지하세요.** 그래프가 구조적으로
   깨진 상태를 "활성화해도 된다"고 판단하면 안 됩니다 — 이 경우는 판단의 여지가 없는
   안전 규칙입니다. structure가 poor가 아닐 때만 결과 등급과 종합해 재량껏 판단하세요.
9. action.note는 왜 그 등급을 줬는지 1~2문장으로 구체적으로 쓰세요("원인: ..." 같은
   기계적 문구를 그대로 베끼지 말고, 당신이 종합적으로 본 근거를 쓰세요).

출력은 반드시 지정된 JSON 스키마(report, action)를 따르세요."""

_RESPONSE_SCHEMA = {
    "name": "simulation_report",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "report": {"type": "string", "description": "마크다운 보고서 전문(## 한눈에 보기로 시작)"},
            "action": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "level": {"type": "string", "enum": ["poor", "warn", "good"]},
                    "note": {"type": "string", "description": "이 등급을 준 구체적 근거 1~2문장"},
                },
                "required": ["level", "note"],
            },
        },
        "required": ["report", "action"],
    },
}


def narrate_report(facts: dict[str, Any]) -> dict[str, Any] | None:
    """`facts` → `{"report": 마크다운, "action": {level, note}}`. 실패 시 None(호출부가
    템플릿 폴백 + 결정론적 action을 유지)."""
    try:
        resp = _openai().chat.completions.create(
            # gpt-5-mini류는 커스텀 temperature 미지원(기본 1만 허용) — 2026-08-18 실측.
            model=settings.model_heavy, reasoning_effort=settings.model_heavy_reasoning_effort, timeout=45,
            response_format={"type": "json_schema", "json_schema": _RESPONSE_SCHEMA},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
            ],
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        report = str(data.get("report") or "").strip()
        if not report:
            return None
        return {"report": report, "action": data.get("action")}
    except Exception:  # noqa: BLE001 — 서술 실패는 시뮬레이션 실패가 아니다
        return None
