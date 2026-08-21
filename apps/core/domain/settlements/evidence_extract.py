"""증빙 판독 호출 — 업로드된 첨부를 ai 비전 도구에 넘기고 결과를 저장한다.

## 왜 업로드 시점인가

추출 결과(`Attachment.extracted`)는 **판정이 쓰는 사실**이다(참석 인원·사전승인 여부…).
제출 이후에 뽑으면 이미 판정이 끝난 뒤라 쓸 데가 없고, 사람이 별도 버튼을 눌러야 하면
아무도 안 누른다. 그래서 파일이 들어오는 그 자리에서 돈다.

## 왜 `on_commit`인가

비전 판독은 이미지 토큰이 붙어 수십 초가 걸린다. 업로드 트랜잭션 안에서 부르면 그동안
DB 커넥션을 붙들고, 판독이 실패하면 **업로드까지 롤백된다** — 파일은 이미 받아 놨는데
기록이 사라지는 게 제일 나쁘다. 커밋 후에 돌리고, 실패는 `extraction_status=FAILED`와
사유로 남긴다(`risk_review.py`와 같은 판단).

## 관측 계약을 여기서 깨뜨리지 않는다

ai가 돌려준 `extracted`를 **그대로** 저장한다. 빈 값을 0/False로 채우지 않는다 —
「확인했는데 없음」과 「안 봤음」이 섞이면 미해소 가드가 잡아야 할 걸 놓친다
(`attachments.py` 모듈 docstring).
"""
from __future__ import annotations

import logging

import httpx
from django.conf import settings
from django.db import transaction as db_tx
from django.utils import timezone

from .attachments import Attachment, ExtractionStatus

logger = logging.getLogger(__name__)

#  비전 호출은 페이지 수만큼 이미지 토큰이 붙는다(`VISION_MAX_PAGES` 상한 있음).
TIMEOUT = 90.0


def schedule(attachment: Attachment) -> None:
    """커밋 후 판독을 예약한다.

    테스트(`TestCase`)는 트랜잭션을 롤백하므로 콜백이 자동으로 뜨지 않는다 —
    검증하려면 `captureOnCommitCallbacks(execute=True)`를 쓴다.
    """
    db_tx.on_commit(lambda: run(attachment.pk))


def run(attachment_id: int) -> Attachment | None:
    """ai `/agent/extract-evidence` 호출 → 결과 저장. 실패해도 예외를 올리지 않는다.

    **id로 다시 읽는다** — 예약 시점의 객체를 붙들고 있으면 그 사이 사람이 고친 값을
    되돌려 쓰게 된다(커밋 후 실행이라 시차가 있다).
    """
    att = Attachment.objects.filter(pk=attachment_id).first()
    if att is None:
        return None
    if not att.file_ref:
        att.extraction_status = ExtractionStatus.FAILED
        att.error = "파일 경로가 없어 판독할 수 없습니다."
        att.save(update_fields=["extraction_status", "error"])
        return att

    Attachment.objects.filter(pk=att.pk).update(extraction_status=ExtractionStatus.RUNNING)
    try:
        resp = httpx.post(
            f"{settings.AI_BASE_URL}/agent/extract-evidence",
            json={"file_ref": att.file_ref, "kind": att.kind},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        result = resp.json()
    except Exception as exc:  # noqa: BLE001  — 미기동·타임아웃·5xx 전부
        logger.warning("extract-evidence 호출 실패(attachment=%s): %s", att.pk, exc)
        att.extraction_status = ExtractionStatus.FAILED
        att.error = f"판독 호출 실패: {exc}"
        att.save(update_fields=["extraction_status", "error"])
        return att

    #  ai가 판단한 상태를 그대로 받는다 — 계약서·기타처럼 뽑을 사실이 정의돼 있지 않은
    #  종류는 `SKIPPED`로 돌아온다. 여기서 DONE으로 바꿔치면 "판독했다"는 거짓이 남는다.
    att.extraction_status = result.get("extraction_status") or ExtractionStatus.DONE
    att.extracted = result.get("extracted") or {}
    att.field_confidence = result.get("field_confidence") or {}
    att.evidence_spans = result.get("evidence_spans") or []
    att.extractor_version = str(result.get("extractor_version") or "")[:32]
    att.extracted_at = timezone.now()
    att.error = "\n".join(result.get("warnings") or [])
    att.save(update_fields=[
        "extraction_status", "extracted", "field_confidence", "evidence_spans",
        "extractor_version", "extracted_at", "error",
    ])
    logger.info(
        "extract-evidence 저장(attachment=%s kind=%s): status=%s facts=%d",
        att.pk, att.kind, att.extraction_status, len(att.extracted),
    )
    return att
