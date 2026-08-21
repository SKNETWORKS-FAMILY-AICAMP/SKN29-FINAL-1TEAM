"""`/agent/extract` 진입점 회귀 — 증빙자료 추출 Agent의 실제 호출 지점(2026-08-21).

`app/vision/read_receipt`·`read_evidence_document`(2026-08-18)는 판독 로직 자체는 완성돼
있었지만 MCP 서버에 등록만 됐을 뿐 아무도 부르지 않았다. 여기서 지키는 것:
  ① `kind=RECEIPT`는 `read_receipt`로, 그 외는 `read_evidence_document`로 분기한다.
  ② 판독 실패(`VisionError`)는 502로 올린다 — 폴백으로 덮지 않는다.
  ③ 응답이 `Attachment` 저장 계약(extracted/fieldConfidence/evidenceSpans/extractorVersion)과 같은 모양이다.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api.extract import ExtractRequest, extract
from app.vision.client import VisionError


def test_receipt_kind_calls_read_receipt():
    with patch("app.vision.read_receipt") as mocked:
        mocked.return_value = {
            "extraction_status": "DONE",
            "extracted": {"dining.includes_alcohol": True},
            "field_confidence": {"dining.includes_alcohol": 0.8},
            "evidence_spans": [],
            "extractor_version": "vision-receipt-1",
            "warnings": [],
        }
        result = extract(ExtractRequest(file_ref="receipts/1.jpg", kind="RECEIPT"))

    mocked.assert_called_once_with("receipts/1.jpg")
    assert result["extractionStatus"] == "DONE"
    assert result["extracted"] == {"dining.includes_alcohol": True}
    assert result["extractorVersion"] == "vision-receipt-1"


def test_non_receipt_kind_calls_read_evidence_document():
    with patch("app.vision.read_evidence_document") as mocked:
        mocked.return_value = {
            "extraction_status": "DONE",
            "extracted": {"approval.pre_approval_obtained": True},
            "field_confidence": {"approval.pre_approval_obtained": 0.9},
            "evidence_spans": [],
            "extractor_version": "vision-doc-1",
            "warnings": [],
        }
        result = extract(ExtractRequest(file_ref="attachments/2.pdf", kind="PRE_APPROVAL"))

    mocked.assert_called_once_with("attachments/2.pdf", "PRE_APPROVAL")
    assert result["extracted"] == {"approval.pre_approval_obtained": True}


def test_vision_failure_reports_502_not_a_silent_fallback():
    with patch("app.vision.read_evidence_document", side_effect=VisionError("파일이 없습니다")):
        with pytest.raises(HTTPException) as exc_info:
            extract(ExtractRequest(file_ref="attachments/missing.pdf", kind="TRIP_PLAN"))

    assert exc_info.value.status_code == 502
    assert "파일이 없습니다" in exc_info.value.detail
