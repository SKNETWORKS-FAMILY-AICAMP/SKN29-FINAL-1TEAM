"""보완요청·반려 **사유 초안** — Draft Agent가 판정 결과와 내역을 보고 채운다.

## 왜 초안을 만들어 주나

사유는 지출자가 **읽고 고쳐야 하는 글**이다. 그런데 결정하는 사람 입장에선 매번 처음부터
쓰는 일이라, 실제로는 "증빙 누락" 같은 라벨만 남고 무엇을 어떻게 보완해야 하는지가
비어 있게 된다. 판정은 이미 사유 코드(`rule_flags`)와 내역을 갖고 있으므로, 그걸 문장으로
펴 주면 결정자가 **지우고 고치는 일**만 하면 된다.

**대신 대신 결정해 주지는 않는다.** 초안은 화면에서 그대로 편집 가능하고, 저장되는 건
사람이 최종적으로 보낸 문구다.

## 어휘를 서버가 갖는 이유

사유 선택지(`RETURN_REASONS`/`REJECT_REASONS`)는 화면과 LLM이 **같은 목록**을 써야 한다.
프론트에 상수로 두면 LLM이 목록에 없는 값을 만들어도 아무도 모르고, 화면 칩과 어긋난
문자열이 그대로 저장된다(플래그 라벨 사전이 백엔드 27 vs 프론트 9로 갈렸던 것과 같은 종류).

## 실패해도 빈손으로 두지 않는다

ai가 안 떠 있거나 LLM이 실패하면 **판정 플래그에서 규칙 기반으로** 문장을 만든다.
지어내는 게 아니라 이미 확정된 사유 코드의 설명을 잇는 것이라 사실과 어긋나지 않는다.
"""
from __future__ import annotations

import logging

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

TIMEOUT = 30.0

#: 사유 선택지 — 화면 칩과 LLM 출력 enum이 **같은 목록**을 본다.
RETURN_REASONS = ["증빙 누락", "건당 한도 초과", "업무관련성 소명 부족", "사전승인 누락", "기타"]
REJECT_REASONS = ["명백한 규정 위반", "사적 사용 의심", "허위 증빙 의심", "중복 제출", "기타"]
#: 승인 사유는 **AI·룰과 다르게 판단할 때만** 받는다 — 권고대로 승인하는 건 설명할 게 없다.
#  그래서 목록이 "왜 기계 판단을 따르지 않았는가"에 대한 답으로 구성된다.
APPROVE_REASONS = [
    "업무관련성 확인됨", "증빙 별도 확인", "규정상 예외 인정",
    "AI 과탐지(오탐)", "경미하여 통과", "기타",
]

#: 판정 사유 코드 → 기본 선택지. LLM이 실패했을 때 쓰는 폴백 매핑이고, LLM이 있을 때도
#  "이 코드면 보통 이 사유"라는 힌트로 프롬프트에 함께 넘긴다.
FLAG_TO_REASON = {
    "EVIDENCE_MISSING": "증빙 누락",
    "RECEIPT_ILLEGIBLE": "증빙 누락",
    "PARTICIPANT_LIST_REQUIRED": "증빙 누락",
    "PURPOSE_UNCLEAR": "업무관련성 소명 부족",
    "CATEGORY_MISSING": "업무관련성 소명 부족",
    "ACTUAL_USER_REQUIRED": "업무관련성 소명 부족",
    "PRE_APPROVAL_MISSING": "사전승인 누락",
    "POST_APPROVAL_REQUIRED": "사전승인 누락",
    "DAILY_LIMIT_OVER": "건당 한도 초과",
    "MONTHLY_LIMIT_OVER": "건당 한도 초과",
    "PER_PERSON_LIMIT_OVER": "건당 한도 초과",
    "LODGING_LIMIT_OVER": "건당 한도 초과",
    "HIGH_AMOUNT": "건당 한도 초과",
    "PROHIBITED_MERCHANT": "명백한 규정 위반",
    "PERSONAL_USE_SUSPECTED": "사적 사용 의심",
    "SPLIT_PAYMENT_SUSPECTED": "중복 제출",
}


DECISIONS = {"APPROVE": APPROVE_REASONS, "RETURN": RETURN_REASONS, "REJECT": REJECT_REASONS}


def options(decision: str) -> list[str]:
    return DECISIONS.get(decision, RETURN_REASONS)


def divergence(settlement, decision: str) -> dict:
    """이 결정이 **기계 판단과 다른가** — 화면이 사유를 받을지 정하는 근거.

    판별 로직을 프론트에 복사하지 않는다(사례 기록도 같은 규약을 쓴다 —
    `domain/risk/decision_cases.expected_decision`).
    """
    from domain.risk.decision_cases import expected_decision

    expected, source = expected_decision(settlement)
    return {
        "expected": expected,
        "expectedFrom": source,
        "diverges": bool(expected) and expected != decision,
    }


def build_context(settlement, decision: str) -> dict:
    """LLM에 넘길 사실 묶음 — **판정이 실제로 남긴 것만** 담는다.

    사유 코드는 라벨·설명까지 펴서 넘긴다. 코드만 주면 모델이 `EVIDENCE_MISSING`을
    제 나름대로 해석해 없는 규정을 지어낸다.
    """
    from domain.policies.flags import describe, label_map

    tx = settlement.transaction
    labels = label_map()
    flags = [describe(f, labels) for f in (settlement.rule_flags or [])]
    return {
        "decision": decision,
        "options": options(decision),
        "settlement": {
            "id": settlement.pk,
            "merchant": tx.merchant if tx else "",
            "amount": int(tx.amount) if tx else 0,
            "date": tx.ts.date().isoformat() if tx and tx.ts else "",
            "category": settlement.category or settlement.ai_category or "",
            "purpose": settlement.purpose or "",
            "merchant_industry": settlement.merchant_industry or "",
            "has_receipt": bool(tx and tx.receipts.exclude(status="MISSING").exists()) if tx else False,
        },
        "judgement": {
            "decision": settlement.rule_decision or "",
            "flags": [
                {
                    "code": f["code"], "label": f["label"], "description": f["description"],
                    "arg": f["arg"], "owner": f["ownerLabel"] or f["owner"],
                }
                for f in flags
            ],
        },
        # "이 코드면 보통 이 사유" — 모델이 목록 밖 값을 만들지 않게 하는 힌트.
        "reason_hints": {f["code"]: FLAG_TO_REASON[f["code"]] for f in flags if f["code"] in FLAG_TO_REASON},
        #  "AI는 이렇게 봤는데 사람은 다르게 판단한다" — 승인 사유 초안의 전제가 된다.
        "divergence": divergence(settlement, decision),
    }


def fallback(context: dict) -> dict:
    """ai 없이 만드는 초안 — 확정된 사유 코드의 설명을 잇는다(지어내지 않는다)."""
    flags = context["judgement"]["flags"]
    hints = context["reason_hints"]
    reason = next((hints[f["code"]] for f in flags if f["code"] in hints), options(context["decision"])[-1])

    if not flags:
        detail = ""
    elif context["decision"] == "APPROVE":
        #  승인은 **기계 판단을 따르지 않은 이유**를 적는 자리다. 플래그 설명을 그대로
        #  이어붙이면 "이래서 문제다"만 남아 승인 사유가 되지 않는다 — 사람이 채우게 둔다.
        detail = ""
        reason = APPROVE_REASONS[0]
    else:
        parts = [f"{f['label']}: {f['description']}" for f in flags if f.get("description")]
        detail = " ".join(parts)
        if context["decision"] == "RETURN":
            detail += " 해당 내용을 보완해 다시 제출해 주세요."
    return {"reason": reason, "detail": detail, "source": "fallback"}


def draft(settlement, decision: str) -> dict:
    """사유 초안 1건. **실패해도 예외를 올리지 않는다** — 결정 자체를 막으면 안 된다."""
    context = build_context(settlement, decision)
    try:
        resp = httpx.post(
            f"{settings.AI_BASE_URL}/agent/decision-reason", json=context, timeout=TIMEOUT,
        )
        resp.raise_for_status()
        result = resp.json()
    except Exception as exc:  # noqa: BLE001  — 미기동·타임아웃·5xx 전부
        logger.info("decision-reason 초안 생성 폴백(settlement=%s): %s", settlement.pk, exc)
        return {**fallback(context), "options": context["options"],
                "divergence": context["divergence"]}

    reason = str(result.get("reason") or "").strip()
    # 목록 밖 값은 버린다 — 화면 칩과 어긋난 문자열이 그대로 저장되면 집계가 갈린다.
    if reason not in context["options"]:
        reason = fallback(context)["reason"]
    return {
        "reason": reason,
        "detail": str(result.get("detail") or "").strip(),
        "source": "ai",
        "options": context["options"],
        "divergence": context["divergence"],
    }
