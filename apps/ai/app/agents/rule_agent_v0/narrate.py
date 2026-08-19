# apps/ai/app/agents/rule_agent_v0/narrate.py
"""Rule Agent — 시뮬레이션 보고서 서술 생성.

`apps/core/domain/policies/simulation.py::_render_template_report()`가 원래 담당하던
"통계·판정을 사람이 읽을 마크다운으로 편성"하는 일 중 **서술문 작성만** LLM에 맡긴다.
판정·통계·구조 평가 자체는 Django가 룰 엔진으로 이미 확정한 값이고(`facts` 인자), 여기서는
그 값을 **재계산하거나 바꾸지 않는다** — LLM은 같은 사실을 놓고 문장만 쓴다. 그래서 프롬프트가
숫자를 임의로 만들지 않도록 "facts에 없는 수치를 지어내지 말라"를 명시한다.

호출부(`views.py` RuleGraphViewSet.simulate)는 이 함수가 실패해도 시뮬레이션 자체를
실패시키지 않는다 — Django `simulation.py`의 결정론적 템플릿(`_render_template_report`)이
항상 폴백으로 남아 있다(§13.3, `rule-agent-v1-implementation.md`).
"""
from __future__ import annotations

import json
from typing import Any

from .agent import _openai
from .settings import settings

_SYSTEM_PROMPT = """당신은 법인카드 정산 룰 콘솔의 시뮬레이션 보고서를 작성하는 보조입니다.
회계 담당자가 이 룰 그래프를 활성화해도 되는지 판단하는 데 씁니다.

원칙:
1. 입력으로 주어진 JSON(facts)에 있는 사실만 사용하세요 — 숫자·건수·판정 결과를 지어내거나
   반올림 이상으로 바꾸지 마세요. facts에 없는 내용은 쓰지 마세요.
2. **반드시 `## 한눈에 보기`로 시작하세요.** 회계 담당자가 이 섹션만 읽어도 판단할 수
   있도록 최대 3~4줄로 압축: ①권장 처리 결론(활성화해도 되는지) ②가장 중요한 이유
   1~2개 ③가장 먼저 확인해야 할 것 1개. 여기서는 통계를 나열하지 말고 결론과 핵심
   근거만 — 나머지 디테일은 뒤 섹션에서 다룹니다. 이 섹션이 보고서에서 **가장 중요한
   부분**입니다 — 나머지는 이걸 뒷받침하는 상세 근거일 뿐입니다.
3. `## 한눈에 보기` 다음에 헤딩(##)으로 섹션을 나눠 다음 내용을 반드시 포함하세요:
   개요(무엇을 시뮬레이션했는지 + 판단 근거 + 권장 처리), 그래프 구성 평가, 실행결과
   (테스트케이스 결과 · 실제 내역 결과 · 노드 커버리지), 주의깊게 살펴봐야 할 부분. 이
   섹션들은 "한눈에 보기"의 근거를 자세히 풀어놓는 부분이라 화면에서 기본적으로 접혀
   있습니다 — 필요한 사람만 펼쳐 봅니다.
4. 딱딱한 통계 나열이 아니라, 담당자가 왜 이 결론에 이르렀는지 자연스러운 문장으로
   풀어 쓰세요. 다만 근거가 되는 구체적 수치(건수·비율)는 반드시 문장 안에 남기세요.
5. `watch`(주의사항)가 비어 있으면 "특별히 확인할 점이 없다"는 취지로 짧게 마무리하세요.
6. **숫자만 던지지 말고 "왜 그 숫자가 나왔는지"를 설명하세요.** "테스트 8건 중 8건
   통과했습니다"로 끝내지 말고, `testExamples`/`riskyExamples`에 있는 구체적 사례를
   최소 1개는 실행결과 섹션에 인용해 "이런 식으로 판정됐다"를 보여주세요 — 예: "예를 들어
   `{label}` 건은 `{path}` 경로를 거쳐 `{decision}`으로 판정됐습니다"처럼 실제 값을 채워
   쓰세요. 두 배열이 비어 있으면(사례 없음) 억지로 지어내지 말고 생략하세요."""


def narrate_report(facts: dict[str, Any]) -> str | None:
    """`facts` → 실제 LLM이 작성한 마크다운 보고서. 실패 시 None(호출부가 템플릿 폴백)."""
    try:
        resp = _openai().chat.completions.create(
            # gpt-5-mini류는 커스텀 temperature 미지원(기본 1만 허용) — 2026-08-18 실측.
            model=settings.model_heavy, reasoning_effort=settings.model_heavy_reasoning_effort, timeout=45,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or None
    except Exception:  # noqa: BLE001 — 서술 실패는 시뮬레이션 실패가 아니다
        return None
