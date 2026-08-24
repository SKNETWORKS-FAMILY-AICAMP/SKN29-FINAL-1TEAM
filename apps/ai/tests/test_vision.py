"""비전 판독 2종 회귀 — LLM은 모킹하고 **계약**을 고정한다.

여기서 지키는 것:
  ① **경로 탈출 방어** — `file_ref`는 결국 업로드에서 비롯된 값이다.
  ② **관측 계약** — 경로가 없으면 "안 봤음", 있으면 "관측함". 근거 없는 추출은 버린다.
  ③ **허용 경로 밖은 버린다** — 조립기가 조용히 버리기 전에 여기서 걸러 이유를 남긴다.
  ④ **PDF는 페이지 이미지로 변환된다** — 결재 도장·서명이 텍스트 추출로는 안 잡힌다.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app import media
from app.vision import document, receipt


@pytest.fixture(autouse=True)
def media_root(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_MEDIA_ROOT", str(tmp_path))
    return tmp_path


# ── 경로 방어 ────────────────────────────────────────────────
def test_path_traversal_is_refused():
    for evil in ("../../etc/passwd", "/etc/passwd", "a/../../../secret"):
        with pytest.raises(media.UnsafeMediaPath):
            media.resolve(evil)


def test_normal_relative_path_resolves(media_root):
    assert media.resolve("attachments/1.pdf") == (media_root / "attachments/1.pdf").resolve()


# ── ① 영수증 ─────────────────────────────────────────────────
def _receipt_reply(facts):
    return {
        "merchant": "강남한식당", "amount": 452000, "date": "2026-08-18", "time": "20:41",
        "payment_method": "법인카드", "approval_no": "12345678",
        "line_items": [
            {"name": "한정식", "quantity": 4, "unit_price": 88000, "amount": 352000, "is_alcohol": False},
            {"name": "참이슬", "quantity": 4, "unit_price": 5000, "amount": 20000, "is_alcohol": True},
        ],
        "totals": {"subtotal": 411000, "vat": 41000, "service_charge": None, "total": 452000},
        "facts": facts,
        "warnings": [],
    }


def _fact(path, kind, value, confidence=0.9, quote="근거"):
    base = {"path": path, "value_kind": kind, "boolean": None, "number": None,
            "string": None, "confidence": confidence, "quote": quote}
    base[kind] = value
    return base


def test_receipt_returns_usage_and_facts(media_root):
    (media_root / "r.jpg").write_bytes(b"\xff\xd8\xff")   # 내용은 안 본다(비전 호출은 모킹)
    reply = _receipt_reply([
        _fact("dining.includes_alcohol", "boolean", True, quote="참이슬 4"),
        _fact("category.item_type", "string", "식사"),
    ])
    with patch.object(receipt.client, "ask", return_value=reply):
        out = receipt.read_receipt("r.jpg")

    # 사용내역(화면·초안이 쓰는 값)
    assert out["merchant"] == "강남한식당"
    assert out["amount"] == 452000
    assert len(out["line_items"]) == 2
    # 판정 사실 — Attachment.extracted와 같은 모양
    assert out["extracted"] == {"dining.includes_alcohol": True, "category.item_type": "식사"}
    assert out["field_confidence"]["dining.includes_alcohol"] == 0.9
    assert out["evidence_spans"][0]["quote"] == "참이슬 4"


def test_receipt_drops_paths_outside_the_allowlist(media_root):
    """추출기가 앞서 나가도 판정이 깨지지 않아야 한다 — 단, 버렸다는 사실은 남긴다."""
    (media_root / "r.jpg").write_bytes(b"\xff\xd8\xff")
    reply = _receipt_reply([
        _fact("dining.includes_alcohol", "boolean", False),
        _fact("policy.dining_per_person_limit", "number", 50000),   # 영수증에서 나올 수 없는 값
    ])
    with patch.object(receipt.client, "ask", return_value=reply):
        out = receipt.read_receipt("r.jpg")

    assert "policy.dining_per_person_limit" not in out["extracted"]
    assert out["extracted"]["dining.includes_alcohol"] is False   # 관측한 false는 살아남는다
    assert any("버렸다" in w for w in out["warnings"])


def test_receipt_unobserved_path_is_simply_absent(media_root):
    """「확인했는데 없음(false)」과 「안 보임(경로 없음)」은 다르다."""
    (media_root / "r.jpg").write_bytes(b"\xff\xd8\xff")
    with patch.object(receipt.client, "ask", return_value=_receipt_reply([])):
        out = receipt.read_receipt("r.jpg")
    assert out["extracted"] == {}          # None으로 채우지 않는다 → 미해소 가드가 잡는다


# ── ② 증빙 문서 ───────────────────────────────────────────────
def test_document_extracts_only_kind_targets(media_root):
    (media_root / "d.pdf").write_bytes(b"%PDF-1.4")
    reply = {
        "findings": [
            #  **확인 필드**(문서로 읽어낸 값)다 — 신고 필드(`participants.participant_count`)와
            #  다른 경로이고, 판독기의 `TARGETS`도 확인 필드만 연다(2026-08 인원 축 분리).
            _fact("participants.verified_participant_count", "number", 6, quote="참석자 6명"),
            _fact("participants.verified_external_count", "number", 2, quote="외부 2명"),
            _fact("trip.region_grade", "string", "가", quote="지역 가"),   # 회의록엔 없는 대상
        ],
        "document_summary": "8/18 거래처 미팅",
        "warnings": [],
    }
    with patch.object(document.client, "load_images", return_value=(["img"], [])), \
         patch.object(document.client, "ask", return_value=reply):
        out = document.read_evidence_document("d.pdf", "MEETING_MINUTES")

    assert out["extraction_status"] == "DONE"
    assert out["extracted"]["participants.verified_participant_count"] == 6
    assert isinstance(out["extracted"]["participants.verified_participant_count"], int)
    # 종류에 없는 대상은 버린다 — 회의록에서 지역등급을 찾게 두면 지어낸다.
    assert "trip.region_grade" not in out["extracted"]


def test_document_requires_a_quote(media_root):
    """근거를 못 대는 추출은 받지 않는다 — 감사 때 되짚을 수 없다."""
    (media_root / "d.pdf").write_bytes(b"%PDF-1.4")
    reply = {
        "findings": [_fact("approval.pre_approval_obtained", "boolean", True, quote="  ")],
        "document_summary": "", "warnings": [],
    }
    with patch.object(document.client, "load_images", return_value=(["img"], [])), \
         patch.object(document.client, "ask", return_value=reply):
        out = document.read_evidence_document("d.pdf", "PRE_APPROVAL")
    assert out["extracted"] == {}
    assert any("근거" in w for w in out["warnings"])


def test_document_skips_kinds_without_targets(media_root):
    """뽑을 것이 정의되지 않은 문서에 LLM을 태우면 없는 사실을 지어낸다."""
    with patch.object(document.client, "ask") as ask:
        out = document.read_evidence_document("c.pdf", "CONTRACT")
    ask.assert_not_called()
    assert out["extraction_status"] == "SKIPPED"
    assert out["extracted"] == {}


def test_document_output_matches_attachment_fields(media_root):
    """변환 계층 없이 그대로 저장된다 — 필드 이름이 어긋나면 조용히 유실된다."""
    (media_root / "d.pdf").write_bytes(b"%PDF-1.4")
    reply = {
        "findings": [_fact("approval.pre_approval_obtained", "boolean", True, quote="승인 2026-08-10")],
        "document_summary": "지출품의서", "warnings": [],
    }
    with patch.object(document.client, "load_images", return_value=(["img"], [])), \
         patch.object(document.client, "ask", return_value=reply):
        out = document.read_evidence_document("d.pdf", "PRE_APPROVAL")
    for field in ("extracted", "field_confidence", "evidence_spans", "extractor_version"):
        assert field in out, field


# ── PDF 래스터화 ──────────────────────────────────────────────
def test_pdf_is_rendered_to_page_images(media_root):
    """텍스트만 뽑으면 결재 도장·서명이 통째로 빠진다 — 페이지를 이미지로 만든다."""
    pdf_path = media_root / "one.pdf"
    _write_minimal_pdf(pdf_path)
    images, warnings = document.client.load_images(pdf_path)
    assert len(images) == 1
    assert images[0].startswith("data:image/png;base64,")
    assert warnings == []


def test_page_cap_is_reported_not_silent(media_root):
    pdf_path = media_root / "three.pdf"
    _write_minimal_pdf(pdf_path, pages=3)
    images, warnings = document.client.load_images(pdf_path, max_pages=2)
    assert len(images) == 2
    assert any("앞 2쪽만" in w for w in warnings)   # 잘랐으면 잘랐다고 말한다


def _write_minimal_pdf(path: Path, pages: int = 1) -> None:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument.new()
    for _ in range(pages):
        pdf.new_page(200, 200)
    pdf.save(str(path))
