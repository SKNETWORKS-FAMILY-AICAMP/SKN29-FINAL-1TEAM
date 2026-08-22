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

## 사용내역(가맹점·금액·일시)은 「비어 있는 자리에만」 채운다

`read_receipt`는 판정 사실뿐 아니라 **사용내역**(가맹점·금액·결제일시)도 읽는다. 그동안
그 값은 여기서 통째로 버려졌다 — 영수증을 올려도 거래 원장은 사용자가 타이핑한 값 그대로였다.

지금은 `_apply_receipt_basics()`가 거래에 반영하되, **`basicsPending`인 거래에만** 넣는다:
  · ERP 수집 건은 카드사 원장이 정본이다 — 영수증이 원장을 덮으면 안 된다(부분취소·팁으로
    금액이 다를 수 있고, 그때 맞는 쪽은 원장이다).
  · 사람이 직접 친 값도 덮지 않는다. 사용자가 보는 앞에서 값이 바뀌면 무엇이 사실인지
    알 수 없게 된다.
읽지 못한 항목은 그대로 둔다(빈 값으로 덮어쓰지 않는다).

## 관측 계약을 여기서 깨뜨리지 않는다

ai가 돌려준 `extracted`를 **그대로** 저장한다. 빈 값을 0/False로 채우지 않는다 —
「확인했는데 없음」과 「안 봤음」이 섞이면 미해소 가드가 잡아야 할 걸 놓친다
(`attachments.py` 모듈 docstring).
"""
from __future__ import annotations

import logging
from datetime import datetime, time

import httpx
from django.conf import settings
from django.db import transaction as db_tx
from django.utils import timezone

from .attachments import Attachment, AttachmentKind, ExtractionStatus

logger = logging.getLogger(__name__)

#  비전 호출은 페이지 수만큼 이미지 토큰이 붙는다(`VISION_MAX_PAGES` 상한 있음).
TIMEOUT = 90.0


#: 사용자가 값을 안 넣고 만든 거래 — 영수증 판독이 채워도 되는 자리라는 표시.
BASICS_PENDING_KEY = "basicsPending"

#: 가맹점을 아직 모를 때 넣어 두는 값(`SettlementViewSet.create`).
PLACEHOLDER_MERCHANT = "미상 가맹점"


def _apply_receipt_basics(att: Attachment, result: dict) -> list[str]:
    """영수증이 읽은 사용내역을 거래에 반영한다. 반영한 항목 이름을 돌려준다.

    `basicsPending`이 아닌 거래는 **건드리지 않는다**(모듈 docstring 참조).
    """
    from django.utils.dateparse import parse_date, parse_time

    settlement = att.settlement
    tx = getattr(settlement, "transaction", None)
    if tx is None or not (tx.raw_payload or {}).get(BASICS_PENDING_KEY):
        return []

    applied: list[str] = []
    fields: list[str] = []

    merchant = str(result.get("merchant") or "").strip()
    if merchant and (not tx.merchant or tx.merchant == PLACEHOLDER_MERCHANT):
        tx.merchant = merchant[:200]
        fields.append("merchant")
        applied.append("가맹점")

    amount = result.get("amount")
    if isinstance(amount, (int, float)) and amount > 0 and int(tx.amount or 0) == 0:
        tx.amount = int(amount)
        fields.append("amount")
        applied.append("금액")

    #  날짜만 읽히고 시각이 없으면 **시각을 지어내지 않는다** — 정오로 밀면 심야 판정이
    #  조용히 뒤집힌다(`SettlementViewSet.update`가 날짜 수정에서 같은 이유로 시각을 보존한다).
    day = parse_date(str(result.get("date") or "")[:10])
    if day is not None:
        clock = parse_time(str(result.get("time") or "")[:5]) or timezone.localtime(tx.ts).time()
        tx.ts = timezone.make_aware(datetime.combine(day, time(clock.hour, clock.minute)))
        fields.append("ts")
        applied.append("결제일시")

    if not fields:
        return []

    #  다 채웠으면 표시를 내린다 — 다음 영수증(재업로드)이 확정된 값을 덮지 않게.
    payload = dict(tx.raw_payload or {})
    payload[BASICS_PENDING_KEY] = False
    payload["basicsFilledBy"] = "RECEIPT_VISION"
    tx.raw_payload = payload
    fields.append("raw_payload")

    tx.save(update_fields=fields)
    logger.info("영수증 판독으로 거래 기본 내역 반영(tx=%s): %s", tx.pk, ", ".join(applied))
    return applied


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
    #  판정 사실과 사용내역은 **다른 축**이다 — 사실은 위에서 그대로 저장하고,
    #  사용내역은 거래 원장에 「비어 있는 자리에만」 반영한다.
    if att.kind == AttachmentKind.RECEIPT:
        try:
            _apply_receipt_basics(att, result)
        except Exception as exc:  # noqa: BLE001
            #  기본 내역 반영이 실패해도 추출 결과는 이미 저장됐다 — 되돌리지 않는다.
            logger.warning("영수증 기본 내역 반영 실패(attachment=%s): %s", att.pk, exc)

    logger.info(
        "extract-evidence 저장(attachment=%s kind=%s): status=%s facts=%d",
        att.pk, att.kind, att.extraction_status, len(att.extracted),
    )
    return att
