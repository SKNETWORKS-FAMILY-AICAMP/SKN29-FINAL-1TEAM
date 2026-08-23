"""Risk Review Agent 호출 — 판정이 `IN_REVIEW`로 넘긴 건에 이상탐지·RAG 검증을 붙인다.

**왜 뷰가 아니라 여기인가**: 예전에는 `SettlementViewSet.judge` 액션 안에만 있었다. 그래서
제출(`/settlements/submit/`)이 판정을 자동으로 이어 돌리게 바뀐 뒤로는 **정상 흐름에서
Risk Review가 아예 안 돌았다** — 수동으로 `/judge/`를 눌러야만 돌았다. 호출 지점이 여러
곳이면 하나는 반드시 빠진다. 그래서 판정 서비스(`services.judge`) 한 곳에 묶었다.

**왜 `on_commit`인가**: AI 호출은 최대 60초다. 판정 트랜잭션 안에서 부르면 그동안 DB
커넥션과 행 잠금을 붙들고 있게 된다. 커밋 후에 부르면 상태 전이는 이미 확정돼 있고,
AI가 느리거나 죽어도 판정 자체는 영향을 받지 않는다.

**확정 데이터는 Django가 쓴다**(CLAUDE.md §1): FastAPI는 판정 결과를 반환만 하고 저장은
여기서 한다.
"""
from __future__ import annotations

import logging

import httpx
from django.conf import settings
from django.db import transaction as db_tx
from django.utils import timezone

from domain.risk.models import RiskReview

from .models import RiskReviewState, Settlement, SettlementStatus as S

logger = logging.getLogger(__name__)

# 1차 이상탐지 + 2차 RAG 검증(LLM)이 직렬로 얹힌다 — 일반 API보다 넉넉히.
TIMEOUT = 60.0

# FastAPI 2차 검증의 권고 → 회계 결정 코드. SUPPLEMENT는 우리 도메인에서 '보완요청'이다.
RECOMMENDATION_MAP = {"APPROVE": "APPROVE", "SUPPLEMENT": "RETURN", "REJECT": "REJECT"}


def schedule(settlement) -> None:
    """`IN_REVIEW`로 끝난 판정에 한해, 커밋 후 Risk Review를 돌리도록 예약한다.

    **예약과 동시에 `RUNNING`을 기록한다.** 실행이 커밋 후라 그 사이 화면이 목록을
    읽으면 결과가 비어 있는데, 상태가 없으면 "룰 통과라 검토를 안 거친 건"과 구분되지
    않는다 — 실제로 검토 중인 건에 "룰 판정으로 통과된 건입니다"가 떴다.

    테스트(`TestCase`)에서는 트랜잭션이 롤백되므로 콜백이 자동으로 뜨지 않는다 —
    검증하려면 `captureOnCommitCallbacks(execute=True)`를 쓴다.
    """
    if settlement.status != S.IN_REVIEW:
        return
    settlement.risk_review_state = RiskReviewState.RUNNING
    settlement.risk_review_error = ""
    settlement.risk_review_started_at = timezone.now()
    settlement.save(update_fields=[
        "risk_review_state", "risk_review_error", "risk_review_started_at", "updated_at",
    ])
    db_tx.on_commit(lambda: run(settlement))


def run(settlement) -> RiskReview | None:
    """Risk Review Agent(1차 이상탐지 + 2차 RAG 내규검증) 호출·저장.

    실패해도 예외를 올리지 않는다 — 판정과 상태 전이는 이미 확정됐고, AI가 없어도
    검토자가 육안 검토를 계속할 수 있어야 한다. 대신 사유를 로그로 남긴다.
    """
    try:
        resp = httpx.post(
            f"{settings.AI_BASE_URL}/agent/risk-review",
            json={"settlement_id": settlement.id},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        result = resp.json()
    except Exception as exc:  # noqa: BLE001  # 미기동·타임아웃·5xx 전부
        logger.warning("risk-review 호출 실패(settlement=%s): %s", settlement.id, exc)
        # 실패를 상태로 남긴다 — 안 남기면 화면이 「아직 도는 중」과 구분하지 못해
        # 담당자가 오지 않을 결과를 계속 기다린다.
        Settlement.objects.filter(pk=settlement.pk).update(
            risk_review_state=RiskReviewState.FAILED, risk_review_error=str(exc)[:500],
        )
        return None

    stage1 = result.get("stage1_anomaly") or {}
    stage2 = result.get("stage2_rag_review") or {}
    review = RiskReview.objects.create(
        settlement=settlement,
        anomaly_score=stage1.get("anomaly_score", 0.0),
        # 1차 등급(HIGH/MEDIUM/LOW). AI가 판정 시점 임계값으로 매긴 값을 그대로 보존한다 —
        # 예전엔 이 값을 여기서 읽지 않아, AI가 계산해 응답에 실어 보내도 조용히 버려졌다.
        risk_tier=stage1.get("risk_tier", ""),
        #  **채점했는지 여부를 그대로 보존한다.** 옛 응답(status 없음)은 점수가 있으면
        #  정상 채점으로 본다 — 그때는 못 잰 경우도 LOW로 왔으므로 소급 판정은 하지 않는다.
        stage1_status=stage1.get("status", ""),
        stage1_note=str(stage1.get("note") or "")[:300],
        # `reasons`는 1차 feature 기여도(프론트 기존 계약), `anomaly_reasons`는 2차 검토 사유.
        reasons=stage1.get("contribs", []),
        anomaly_reasons=stage2.get("review_reasons", []),
        rag_refs=[
            {
                "title": c.get("quote_summary", ""),
                "source": f"{c.get('doc', '')} {c.get('article', '')}".strip(),
                "kind": "policy",
            }
            for c in stage2.get("citations", [])
        ]
        + [
            {
                "title": sc.get("relevance", ""),
                "source": f"사례 {sc.get('case_id', '')} ({sc.get('outcome', '')})",
                "kind": "case",
            }
            for sc in stage2.get("similar_cases", [])
        ],
        ai_recommendation=RECOMMENDATION_MAP.get(stage2.get("recommendation", ""), ""),
        # LLM 원본 출력은 따로 보존한다 — 기존 `reasons` 계약을 깨지 않기 위해 분리했다.
        stage2_verdict=stage2,
    )
    Settlement.objects.filter(pk=settlement.pk).update(
        risk_review_state=RiskReviewState.DONE, risk_review_error="",
    )
    logger.info(
        "risk-review 저장(settlement=%s): verdict=%s recommendation=%s",
        settlement.id, stage2.get("violation_verdict"), review.ai_recommendation,
    )
    return review
