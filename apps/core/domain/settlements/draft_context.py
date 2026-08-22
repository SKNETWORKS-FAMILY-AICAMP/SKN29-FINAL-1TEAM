"""Draft Agent가 받아 갈 **사실 묶음**을 조립한다.

## 왜 이 모듈이 생겼나

초안 Agent가 지금까지 받은 외부 사실은 가맹점 업종과 분류별 한도 **둘뿐**이었다. 나머지는
화면이 보낸 폼 값(사람이 타이핑한 가맹점·금액)이었고, 그래서 모델이 사실상 "지어낼 수 있는"
자리가 넓었다. 이 모듈은 그 반대를 만든다 — **만들어낼 수 없는 것은 전부 서버가 사실로 넣고,
모델에게는 분류·목적·설명만 남긴다.**

## 판정은 여기서 예측하지 않는다 (중요)

「보완요청/반려될 것 같은가」는 **결정론적 엔진이 이미 답을 갖고 있다**.
`orchestrator.judge(settlement, record=False)`가 감사 로그를 건드리지 않고 실제 판정을
돌려준다(그 통로는 이 용도로 만들어져 있었는데 호출부가 없었다).

그래서 룰 그래프 구조를 LLM에 주지 않는다. 그래프를 주고 순회를 흉내내게 하면
① JSON-Logic 평가·severity 우선순위·미해소 가드까지 맞춰야 해서 틀리고 ② 틀려도 티가
안 나며 ③ 사용자에게는 "AI가 통과라고 했는데 반려됨"이 된다. 엔진이 결정하고 모델은
**그 결과를 사람 말로 옮기기만** 한다(`narrate.py`가 시뮬레이션 보고서에서 쓰는 것과 같은 분업).

## EvalContext는 설명을 달아 보낸다

경로 문자열만 주면 모델이 극성을 추측한다 — `evidence.expense_purpose_missing`처럼 이름과
참/거짓이 뒤집힌 필드가 실재한다. `eval_context.schema_catalog()`의 `desc`를 값에 붙여서
내보낸다(사본을 만들지 않는다).
"""
from __future__ import annotations

import logging
from typing import Any

from domain.policies import orchestrator
from domain.policies.context_builder import policy_field_specs
from domain.policies.eval_context import schema_catalog
from domain.policies.flags import describe as describe_flag
from domain.policies.flags import label_map
from domain.settlements.models import Category, SettlementStatus

logger = logging.getLogger(__name__)

#: 사람에게 되돌아가는 결정 — 이게 나오면 지금 제출해도 다시 돌아온다.
BLOCKING_DECISIONS = {"RETURN", "REJECT"}

#: 보완 맥락으로 실어 보낼 상태 — 「왜 돌아왔는지」를 모르면 같은 실수를 반복한다.
RETURNED_STATUSES = {
    SettlementStatus.RETURNED, SettlementStatus.TEAM_RETURNED, SettlementStatus.TEAM_REJECTED,
}


def _field_descriptions() -> dict[str, str]:
    """`dot-path → 설명`. 별표에서 파생된 동적 `policy.*`도 포함한다."""
    catalog = schema_catalog(policy_field_specs())
    return {
        field["path"]: field["desc"]
        for section in catalog["sections"]
        for field in section["fields"]
    }


def _flatten(ctx: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for section, fields in ctx.items():
        if isinstance(fields, dict):
            for name, value in fields.items():
                out[f"{section}.{name}"] = value
    return out


def _facts(ctx: dict[str, Any], descriptions: dict[str, str]) -> list[dict[str, Any]]:
    """**값이 있는 것만** 내보낸다.

    46칸을 전부 실으면 대부분이 `null`이라 모델의 주의가 흩어진다. 「모른다」는 사실은
    `unresolved`와 판정 플래그(`UNRESOLVED_FACT:*`)가 이미 말해 준다.
    """
    return [
        {"path": path, "value": value, "desc": descriptions.get(path, "")}
        for path, value in sorted(_flatten(ctx).items())
        if value is not None and value != ""
    ]


def _attachments(settlement) -> list[dict[str, Any]]:
    """첨부가 **실제로 읽어낸 것**만. 판독 전·실패도 상태 그대로 싣는다.

    「아직 안 읽었다」와 「읽었는데 없다」를 섞지 않는 것이 증빙 추출의 계약이라
    (`vision/document.py`), 여기서도 상태를 지우지 않는다.
    """
    descriptions = _field_descriptions()
    rows = []
    for a in settlement.attachments.all():
        rows.append({
            "kind": a.kind,
            "kindLabel": a.get_kind_display(),
            "fileName": a.original_name,
            "status": a.extraction_status,
            "facts": [
                {
                    "path": path,
                    "value": value,
                    "desc": descriptions.get(path, ""),
                    "confidence": (a.field_confidence or {}).get(path),
                }
                for path, value in sorted((a.extracted or {}).items())
            ],
        })
    return rows


def _judgement(settlement) -> dict[str, Any]:
    """엔진 dry-run. **상태도 `rule_hits`도 건드리지 않는다.**

    실패해도 초안 작성을 막지 않는다 — 판정 미리보기가 없으면 안내가 빠질 뿐이지만,
    여기서 예외를 올리면 초안 자체가 안 나온다.
    """
    try:
        result = orchestrator.judge(settlement, record=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("판정 미리보기 실패(settlement=%s): %s", settlement.pk, exc)
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}

    labels = label_map()
    return {
        "available": True,
        "decision": result.decision,
        "scope": result.scope,
        "blocking": result.decision in BLOCKING_DECISIONS,
        "flags": [describe_flag(flag, labels) for flag in result.flags],
        "graphs": [
            {
                "scope": run.scope,
                "name": run.graph.name,
                "version": run.graph.version,
                "decision": run.result.decision,
                "path": run.result.path,
            }
            for run in result.runs
        ],
        "unresolved": result.unresolved_policy_fields,
        "evalContext": result.eval_context,
    }


def _return_context(settlement) -> dict[str, Any] | None:
    """보완요청·반려로 돌아온 건이면 **왜 돌아왔는지**.

    사유(사람이 쓴 문장)와 그때의 판정 플래그를 함께 싣는다 — 둘은 다른 축이다.
    회계는 "참석자 명단이 없다"고 쓰고 룰은 `EVIDENCE_MISSING`을 걸 수 있다.
    """
    if settlement.status not in RETURNED_STATUSES:
        return None

    event = (
        settlement.events.filter(to_state=settlement.status)
        .order_by("-created_at")
        .first()
    )
    if event is None:
        return None

    actor = getattr(event, "actor", None)
    return {
        "status": settlement.status,
        "statusLabel": settlement.get_status_display(),
        "reason": event.reason or "",
        "actor": (actor.get_full_name() or actor.username) if actor else "",
        "at": event.created_at.isoformat(),
    }


def build(settlement) -> dict[str, Any]:
    """Draft Agent 입력 한 묶음."""
    tx = settlement.transaction
    card = getattr(tx, "card", None)
    judgement = _judgement(settlement)
    descriptions = _field_descriptions()
    ctx = judgement.get("evalContext") or {}

    return {
        "settlementId": settlement.pk,
        "status": settlement.status,
        # ── 만들어낼 수 없는 것 (ERP 수집·영수증 비전·카드 원장에서 온다) ──
        "basics": {
            "merchant": tx.merchant if tx else "",
            "amount": int(tx.amount) if tx else 0,
            "date": tx.ts.date().isoformat() if tx else "",
            "time": tx.ts.strftime("%H:%M") if tx else "",
            "cardType": card.card_type if card else "",
            "cardName": (card.name or "") if card else "",
            "industry": settlement.merchant_industry or "",
            "industryCode": settlement.merchant_industry_code or "",
        },
        # ── 지금 저장돼 있는 값 (사람 확정 / AI 제안) ──
        "current": {
            "category": settlement.category or "",
            "aiCategory": settlement.ai_category or "",
            "aiSuggested": settlement.ai_suggested,
            "purpose": settlement.purpose or "",
            "headcount": settlement.headcount,
        },
        "categories": list(Category.values),
        "attachments": _attachments(settlement),
        "facts": _facts(ctx, descriptions),
        "judgement": {k: v for k, v in judgement.items() if k != "evalContext"},
        "returnContext": _return_context(settlement),
    }
