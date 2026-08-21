"""증빙자료 추출 Agent 진입점 (`/agent/extract`) — `_context/evidence-extraction-agent.md`.

판독 로직 자체(비전 프롬프트·관측 계약·구조화 출력)는 `app/vision/`에 이미 있다
(2026-08-18, MCP tool `read_receipt`/`read_evidence_document`로 노출). 여기서 하는 일은
Django가 첨부(`Attachment`) 하나를 올렸을 때 그 로직을 **호출하는 진입점을 여는 것**뿐이다
— 그전까지는 두 도구 다 MCP 서버에 등록만 돼 있을 뿐 아무도 부르지 않았다.

`kind=RECEIPT`는 `read_receipt`(사용내역+사실), 그 외는 `read_evidence_document`(사실만)로
분기한다 — 두 도구의 반환 모양이 다르므로(전자는 merchant/amount 등도 포함) 여기서
`Attachment` 계약(`extracted`/`field_confidence`/`evidence_spans`)만 추려 돌려준다.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.vision.client import VisionError

logger = logging.getLogger(__name__)
router = APIRouter()


class ExtractRequest(BaseModel):
    file_ref: str
    kind: str


@router.post("/extract")
def extract(req: ExtractRequest) -> dict:
    """첨부 1건 판독 → `Attachment` 저장 계약과 같은 모양으로 반환.

    실패를 폴백으로 덮지 않는다(이 프로젝트 전반의 원칙) — 판독 실패는 502로 올리고,
    Django가 `Attachment.extraction_status=FAILED`에 사유를 그대로 남긴다.
    """
    kind = (req.kind or "").upper()
    try:
        if kind == "RECEIPT":
            from app.vision import read_receipt

            raw = read_receipt(req.file_ref)
        else:
            from app.vision import read_evidence_document

            raw = read_evidence_document(req.file_ref, kind)
    except VisionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("extract 실패: file_ref=%s kind=%s", req.file_ref, kind)
        raise HTTPException(status_code=502, detail=f"판독 실패: {type(exc).__name__}: {exc}") from exc

    return {
        "extractionStatus": raw.get("extraction_status", "DONE"),
        "extracted": raw.get("extracted", {}),
        "fieldConfidence": raw.get("field_confidence", {}),
        "evidenceSpans": raw.get("evidence_spans", []),
        "extractorVersion": raw.get("extractor_version", ""),
        "warnings": raw.get("warnings", []),
        "documentSummary": raw.get("document_summary", ""),
    }
