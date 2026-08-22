"""제출 직전 준비 — 문체 다듬기 + 판정 미리보기 + 「멈춰 세울지」 판단.

## 왜 서버가 판단하는가

「조용히 다듬어 자동 제출」이 기본 동작이다. 그래서 **언제 사람을 멈춰 세울지**가 이
기능의 전부다. 화면이 그 기준을 갖고 있으면 곧 서버와 갈린다(팝업 조건이 두 곳에 생긴다).

멈춰 세우는 기준은 셋뿐이다:
  · 다듬은 문장이 **원문에 없던 내용**을 담았다 (`submit_polish`가 기계적으로 대조)
  · 지출 목적이 **정보가 부족**하다
  · 판정 미리보기가 **RETURN/REJECT** 다 — 지금 제출하면 되돌아온다

`REVIEW`로는 멈추지 않는다. 룰이 자동 판단하지 않고 회계가 보는 것뿐이라 지출자가 고칠
것이 없고, 여기서 팝업을 띄우면 정상 건마다 사람이 멈춰 선다(요구사항: IN_REVIEW는 정상).

## AI가 죽어도 제출은 막지 않는다

다듬기는 편의 기능이다. 실패하면 원문 그대로 두고 판정 안내만 낸다.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from django.conf import settings

from . import draft_context

logger = logging.getLogger(__name__)

TIMEOUT = 20.0

#: 사람을 멈춰 세우는 안내 등급.
CONFIRM_LEVELS = {"blocker", "warn"}


def _polish(purpose: str, context_hint: str) -> dict[str, Any]:
    try:
        resp = httpx.post(
            f"{settings.AI_BASE_URL}/agent/draft/polish",
            json={"purpose": purpose, "contextHint": context_hint},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001  # ai 미기동·타임아웃·5xx 전부
        logger.warning("문체 다듬기 호출 실패 — 원문 유지: %s", exc)
        return {"applied": False, "original": purpose, "polished": purpose, "review": [],
                "diff": {}, "modelReported": {"error": f"{type(exc).__name__}: {exc}"}}


def _judgement_notices(judgement: dict[str, Any]) -> list[dict[str, Any]]:
    """판정 미리보기 → 안내. **여기서 판정을 다시 계산하지 않는다.**"""
    if not judgement.get("available"):
        #  미리보기를 못 얻었다고 제출을 막지 않는다 — 다만 "확인했다"고도 하지 않는다.
        return [{
            "level": "info", "code": "JUDGEMENT_UNAVAILABLE",
            "label": "판정 미리보기 없음",
            "text": "제출 전 판정 미리보기를 확인하지 못했습니다. 제출 후 판정 결과를 확인해 주세요.",
        }]

    decision = judgement.get("decision") or ""
    if decision not in draft_context.BLOCKING_DECISIONS:
        return []

    label = "보완요청" if decision == "RETURN" else "반려"
    head = {
        "level": "blocker", "code": f"PREDICTED_{decision}",
        "label": f"지금 제출하면 {label} 예상",
        "text": f"현재 내용으로는 룰 판정이 「{label}」입니다. 아래 사유를 해소하고 제출하면 왕복을 줄일 수 있습니다.",
    }
    reasons = [
        {
            "level": "blocker",
            "code": f["code"],
            "label": f.get("label") or f["code"],
            "text": f.get("description") or f.get("label") or f["code"],
            "owner": f.get("ownerLabel") or "",
            "severity": f.get("severityLabel") or "",
        }
        for f in (judgement.get("flags") or [])
    ]
    return [head, *reasons]


def prepare(settlement) -> dict[str, Any]:
    """제출 준비. **`settlement.purpose`를 갱신할 수 있다**(다듬기가 적용된 경우).

    Returns:
        ``{purpose, polish, judgement, notices, shouldConfirm}``
    """
    ctx = draft_context.build(settlement)
    judgement = ctx.get("judgement") or {}

    #  맥락 힌트는 **문장에 넣으라는 뜻이 아니다** — 모델이 원문의 뜻을 파악하는 데만 쓴다
    #  (그래서 프롬프트에도 그렇게 명시돼 있다). 사실 자체는 EvalContext가 이미 갖고 있다.
    basics = ctx.get("basics") or {}
    hint = f"가맹점 {basics.get('merchant')}, 금액 {basics.get('amount')}원, 업종 {basics.get('industry') or '미확인'}"

    polish = _polish(settlement.purpose or "", hint)

    if polish.get("applied") and polish.get("polished") and polish["polished"] != (settlement.purpose or ""):
        settlement.purpose = polish["polished"][:300]
        settlement.save(update_fields=["purpose"])

    notices = [*polish.get("review", []), *_judgement_notices(judgement)]
    return {
        "purpose": settlement.purpose or "",
        "polish": polish,
        "judgement": {k: v for k, v in judgement.items() if k != "evalContext"},
        "notices": notices,
        #  info만 있으면 조용히 지나간다 — 그게 이 기능의 기본 동작이다.
        "shouldConfirm": any(n.get("level") in CONFIRM_LEVELS for n in notices),
    }
