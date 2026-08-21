"""처리 사유 초안 — 보완요청/반려 사유를 담당자가 고쳐 쓸 자연스러운 문장으로 정리한다.

이미 확정된 판정 근거(룰 플래그·2차 RAG 검증 사유·1차 이상탐지 사유)를 조합해 1~2문장으로
요약할 뿐이다 — **새로운 판단을 하지 않는다**(그건 이미 룰 엔진·Risk Review Agent가 끝냈다).
RAG 검색도 tool-calling도 없다 — 이미 있는 사실을 문장으로 다듬는 단발 LLM 호출.

**담당자가 그대로 제출하지 않고 고쳐 쓸 걸 전제한다**(2026-08-21 결정) — 프롬프트가 과장·
단정적 표현을 피하게 만드는 이유이자, 초안일 뿐 확정 사유가 아니라는 계약이다. 실패하면
빈 문자열/일반 문구로 얼버무리지 않고 호출부가 에러를 그대로 올린다(`api/decision_reason.py`
가 예외를 삼키지 않음) — "AI가 판단했다"고 오해하지 않도록.
"""
from __future__ import annotations

from openai import OpenAI

from app.config import settings

MODEL = "gpt-4o-mini"

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


SYSTEM_PROMPT = """당신은 법인카드 정산 회계 담당자가 보완요청·반려 사유를 작성하는 걸 돕습니다.
아래 주어진 판정 근거만 바탕으로 사유를 1~2문장의 담백한 한국어 문장으로 정리하세요.

반드시 지켜야 할 규칙:
1. 주어진 근거에 없는 사실을 지어내지 마세요. 근거가 부족하면 있는 것만으로 짧게 쓰세요.
2. 담당자가 이 초안을 그대로 제출하지 않고 검토·수정할 것을 전제로, 과장하거나 단정적으로
   쓰지 마세요("명백히", "확실히" 같은 표현 대신 근거를 있는 그대로 서술하세요).
3. 반려(REJECT)는 최종 처리이니 사유를 분명히 밝히고, 보완요청(RETURN)은 담당자가 무엇을
   보완해야 하는지 구체적으로 안내하는 톤으로 쓰세요.
4. 사유 문장만 반환하세요 — 인사말·따옴표·"사유:" 같은 접두어 없이."""

USER_PROMPT_TEMPLATE = """[처리 구분] {decision_label}
[선택한 사유 분류] {reason_category}

[대상 건]
가맹점: {merchant} / 금액: {amount}원 / 분류: {category}
지출 목적: {purpose}

[판정 근거]
- 룰 플래그: {rule_flags}
- 2차 내규검증 판정: {violation_verdict}
- 2차 내규검증 사유: {review_reasons}
- 1차 이상탐지 사유: {anomaly_reasons}"""

_DECISION_LABEL = {"RETURN": "보완요청", "REJECT": "반려"}


def draft(payload: dict) -> str:
    """근거를 문장으로 정리한다. 반환이 빈 문자열이면 호출부가 실패로 다뤄야 한다."""
    decision = payload.get("decision", "")
    user_prompt = USER_PROMPT_TEMPLATE.format(
        decision_label=_DECISION_LABEL.get(decision, decision),
        reason_category=payload.get("reasonCategory") or "(미지정)",
        merchant=payload.get("merchant", ""),
        amount=payload.get("amount", 0),
        category=payload.get("category", ""),
        purpose=payload.get("purpose") or "(미기재)",
        rule_flags=", ".join(
            f"{f.get('label')}({f.get('severity')})" for f in (payload.get("ruleFlags") or [])
        ) or "(없음)",
        violation_verdict=payload.get("violationVerdict") or "(없음)",
        review_reasons="; ".join(payload.get("reviewReasons") or []) or "(없음)",
        anomaly_reasons=", ".join(payload.get("anomalyReasons") or []) or "(없음)",
    )
    resp = _get_client().chat.completions.create(
        model=MODEL,
        temperature=0.3,
        timeout=20,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    return (resp.choices[0].message.content or "").strip()
