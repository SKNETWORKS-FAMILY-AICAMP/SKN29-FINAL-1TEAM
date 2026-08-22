"""사례 → Chroma(`case_history`) 적재.

## 왜 커밋 후인가

임베딩은 OpenAI 왕복이라 수 초가 걸린다. 결정 트랜잭션 안에서 부르면 그동안 DB 커넥션을
붙들고, 적재가 실패하면 **결정까지 롤백된다** — 회계 담당자가 내린 판단이 AI 인프라 사정으로
사라지는 건 있을 수 없다. 커밋 후에 돌리고 실패는 `index_error`로 남긴다
(`evidence_extract`·`risk_review`와 같은 판단).

## 미적재는 사고가 아니라 상태다

`indexed_at`이 비어 있으면 아직 안 올라간 것이다. 관리자가 나중에 일괄 재적재할 수 있게
`reindex_pending()`을 둔다 — ai가 며칠 꺼져 있었어도 사례가 유실되지 않는다.
"""
from __future__ import annotations

import logging

import httpx
from django.conf import settings
from django.db import transaction as db_tx
from django.utils import timezone

from .models import DecisionCase

logger = logging.getLogger(__name__)

#: 임베딩 왕복. 사례 한 건이라 짧지만 OpenAI 지연을 감안해 여유를 둔다.
TIMEOUT = 30.0


def schedule(case: DecisionCase) -> None:
    """커밋 후 적재를 예약한다.

    테스트(`TestCase`)는 트랜잭션을 롤백하므로 콜백이 자동으로 뜨지 않는다 —
    검증하려면 `captureOnCommitCallbacks(execute=True)`를 쓴다.
    """
    db_tx.on_commit(lambda: index(case.pk))


def index(case_id: int) -> DecisionCase | None:
    """사례 1건을 `case_history`에 upsert. 실패해도 예외를 올리지 않는다.

    **id로 다시 읽는다** — 예약 시점 객체를 붙들면 그 사이 바뀐 값을 되돌려 쓴다.
    """
    case = DecisionCase.objects.filter(pk=case_id).first()
    if case is None:
        return None
    try:
        resp = httpx.post(
            f"{settings.AI_BASE_URL}/embeddings/cases",
            json={"cases": [case.to_payload()]},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001  — 미기동·타임아웃·5xx 전부
        logger.warning("사례 적재 실패(case=%s): %s", case.case_id, exc)
        DecisionCase.objects.filter(pk=case.pk).update(index_error=str(exc)[:500])
        return case

    DecisionCase.objects.filter(pk=case.pk).update(indexed_at=timezone.now(), index_error="")
    logger.info("사례 적재 완료(case=%s)", case.case_id)
    #  `update()`는 메모리의 객체를 갱신하지 않는다 — 호출부가 `indexed_at`으로 성공을
    #  판별하므로 다시 읽어 돌려준다(안 그러면 성공한 적재가 실패로 집계된다).
    case.refresh_from_db()
    return case


def reindex_pending(limit: int = 100) -> tuple[int, int]:
    """아직 안 올라간 사례를 몰아서 적재한다. Returns (시도, 성공).

    ai가 꺼져 있던 동안 쌓인 사례를 되살리는 경로다 — 관리자 CLI(`reindex_cases`)가 부른다.
    """
    pending = list(DecisionCase.objects.filter(indexed_at__isnull=True)[:limit])
    if not pending:
        return 0, 0
    ok = 0
    for case in pending:
        case = index(case.pk)
        ok += bool(case and case.indexed_at)
    return len(pending), ok
