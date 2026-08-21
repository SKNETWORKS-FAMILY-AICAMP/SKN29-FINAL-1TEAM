"""사례 기록 — 회계 담당자가 **AI·룰과 다르게 판단했을 때** 그 판단을 남긴다.

## 언제 남기나

`services.review()`가 사람의 결정을 확정하는 순간, 그 결정이 **AI 권고 또는 룰 판정과
다르면** 사례를 만든다. 일치하면 만들지 않는다 — 사례의 가치는 "AI는 이렇게 봤는데
사람은 다르게 판단했고, 그 이유는 이것이다"에 있고, 일치 건까지 넣으면 검색 상위가
다수결에 묻혀 정작 봐야 할 예외가 밀려난다.

## 무엇과 비교하나

  ① **AI 권고**(`RiskReview.ai_recommendation`)가 있으면 그것과 비교한다.
  ② 없으면(룰이 통과시켜 검토를 안 거친 건) **룰 판정**과 비교한다 —
     `PASS`는 사람의 `APPROVE`에 대응한다. 룰 통과 건을 사람이 되돌린 것도
     "다르게 판단한" 사례다(`services.RULE_OVERRIDE_MARK`가 붙는 그 상황).

## 본문은 스냅샷이다

`text`는 결정 시점의 사실로 조립해 얼려 둔다. 정산은 이후에도 고쳐지는데(보완요청 →
수정 → 재제출) 검색이 지금 값을 따라가면 "그때 왜 그렇게 판단했는가"를 설명할 수 없다.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from .models import DecisionCase

logger = logging.getLogger(__name__)

#: 룰 판정 → 사람 결정의 대응. 룰은 `PASS/RETURN/REJECT/REVIEW`, 사람은 `APPROVE/RETURN/REJECT`다.
#  `REVIEW`는 룰이 **판단을 미룬 것**이라 비교 대상이 아니다(무엇과도 "다르다"고 말할 수 없다).
RULE_TO_HUMAN = {"PASS": "APPROVE", "RETURN": "RETURN", "REJECT": "REJECT"}


def expected_decision(settlement) -> tuple[str, str]:
    """이 건에 대해 **기계가 내놨던 결론**과 그 출처. 없으면 `("", "")`.

    AI 권고를 우선한다 — 검토를 거친 건이라면 그게 사람이 실제로 마주한 제안이다.
    """
    review = settlement.risk_reviews.order_by("-id").first()
    if review and review.ai_recommendation:
        return review.ai_recommendation, DecisionCase.Source.AI
    ruled = RULE_TO_HUMAN.get(settlement.rule_decision or "")
    if ruled:
        return ruled, DecisionCase.Source.RULE
    return "", ""


def _facts(settlement) -> dict:
    tx = settlement.transaction
    return {
        "merchant": tx.merchant if tx else "",
        "amount": int(tx.amount) if tx else 0,
        "date": tx.ts.date().isoformat() if tx and tx.ts else "",
        "category": settlement.category or settlement.ai_category or "",
        "merchant_industry": settlement.merchant_industry or "",
        "purpose": settlement.purpose or "",
        "card_type": tx.card.card_type if (tx and tx.card_id) else "",
    }


def compose_text(settlement, outcome: str, expected: str, source: str, reason: str) -> str:
    """임베딩 대상 본문. **자체로 완결돼야 한다** — 검색이 매칭하는 건 이 문장뿐이다.

    골든 데이터(`app/rag/golden_cases.py`)와 같은 톤으로 맞춘다: 상황 → 판단 → 이유.
    """
    from domain.policies.flags import describe, label_map

    f = _facts(settlement)
    labels = label_map()
    flags = [describe(code, labels)["label"] for code in (settlement.rule_flags or [])]

    head = f"{f['category'] or '분류 미기재'} {f['amount']:,}원, {f['merchant'] or '가맹점 미상'}"
    if f["merchant_industry"]:
        head += f"({f['merchant_industry']})"
    if flags:
        head += f". 판정 사유: {', '.join(flags)}"

    origin = "AI 권고" if source == DecisionCase.Source.AI else "룰 판정"
    #  조사를 받침에 맞춘다 — "보완요청였으나"·"반려으로" 같은 문장이 그대로 임베딩되고
    #  검토 화면 인용문으로도 노출된다. 검색 품질보다 **읽는 사람에 대한 문제**다.
    was = _josa(_label(expected), "이었으나", "였으나")
    to = _josa(_label(outcome), "으로", "로")
    middle = f". {origin}는 {_label(expected)}{was} 회계 담당자는 {_label(outcome)}{to} 판단"
    return f"{head}{middle}. 사유: {reason.strip()}"


def _josa(word: str, with_batchim: str, without: str) -> str:
    """마지막 글자의 받침 유무로 조사를 고른다. 한글이 아니면 받침 없는 쪽."""
    if not word:
        return without
    last = word[-1]
    if not ("가" <= last <= "힣"):
        return without
    return with_batchim if (ord(last) - 0xAC00) % 28 else without


_HUMAN_LABEL = {"APPROVE": "승인", "RETURN": "보완요청", "REJECT": "반려"}


def _label(decision: str) -> str:
    return _HUMAN_LABEL.get(decision, decision or "판단 없음")


def record(settlement, outcome: str, actor=None, reason: str = "") -> DecisionCase | None:
    """사람의 결정이 기계와 다르면 사례를 남긴다. 같거나 비교 대상이 없으면 `None`.

    **실패해도 예외를 올리지 않는다** — 사례 기록이 결정을 되돌리면 안 된다.
    """
    expected, source = expected_decision(settlement)
    if not expected or expected == outcome:
        return None
    if not reason.strip():
        # 사유 없는 사례는 검색돼도 쓸모가 없다("왜 다르게 봤는지"가 사례의 핵심).
        logger.info("사례 기록 생략(settlement=%s): 사유가 비어 있다", settlement.pk)
        return None

    try:
        case = DecisionCase.objects.create(
            settlement=settlement,
            case_id=f"case-s{settlement.pk}-{int(timezone.now().timestamp())}",
            category=settlement.category or settlement.ai_category or "",
            outcome=outcome,
            diverged_from=source,
            expected=expected,
            ai_recommendation=(
                settlement.risk_reviews.order_by("-id").first().ai_recommendation
                if settlement.risk_reviews.exists() else ""
            ),
            rule_decision=settlement.rule_decision or "",
            rule_flags=list(settlement.rule_flags or []),
            reason=reason.strip(),
            text=compose_text(settlement, outcome, expected, source, reason),
            facts=_facts(settlement),
            citation=f"과거 결정사례 #{settlement.pk}",
            decided_by=actor,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("사례 기록 실패(settlement=%s): %s", settlement.pk, exc)
        return None

    logger.info(
        "사례 기록(settlement=%s): %s %s → %s",
        settlement.pk, source, expected, outcome,
    )
    return case
