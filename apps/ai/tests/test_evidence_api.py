"""`/agent/extract-evidence` 회귀 — Django가 첨부 업로드 직후 부르는 결정론적 진입점.

고정하는 계약:
  ① 종류로 갈린다 — `RECEIPT`는 영수증 판독기, 나머지는 문서 판독기.
  ② **영수증 응답에도 `extraction_status`가 붙는다** — Django 저장 계약이 그걸 읽는다.
     여기서 안 채우면 호출부가 종류별로 분기해야 한다.
  ③ **실패를 200으로 덮지 않는다** — 빈 결과를 성공으로 돌려주면 Django가 "판독 완료,
     사실 0건"으로 저장하고 화면은 「확인했는데 없음」으로 읽는다(관측 계약이 깨진다).
  ④ 미디어 루트를 벗어나는 경로는 잘라내지 않고 **거부**한다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import evidence
from app.media import UnsafeMediaPath
from app.main import app

client = TestClient(app, raise_server_exceptions=False)
URL = "/agent/extract-evidence"


def test_영수증은_영수증_판독기로_간다(monkeypatch):
    monkeypatch.setattr(evidence.receipt, "read_receipt", lambda ref: {
        "file_ref": ref, "merchant": "한식당", "amount": 120000,
        "extracted": {"dining.includes_alcohol": True},
        "field_confidence": {"dining.includes_alcohol": 0.9},
        "evidence_spans": [], "extractor_version": "v1", "warnings": [],
    })
    r = client.post(URL, json={"file_ref": "attachments/202608/a.pdf", "kind": "RECEIPT"})
    assert r.status_code == 200
    body = r.json()
    # ② 영수증 판독기는 상태를 안 내지만 저장 계약에는 필요하다 — 여기서 채운다.
    assert body["extraction_status"] == "DONE"
    assert body["extracted"] == {"dining.includes_alcohol": True}
    assert body["merchant"] == "한식당"


def test_그_외_종류는_문서_판독기로_간다(monkeypatch):
    seen = {}

    def _read(ref, kind):
        seen.update(file_ref=ref, kind=kind)
        return {"file_ref": ref, "kind": kind, "extraction_status": "DONE",
                "extracted": {"approval.pre_approval_obtained": True},
                "field_confidence": {}, "evidence_spans": [],
                "document_summary": "", "extractor_version": "v1", "warnings": []}

    monkeypatch.setattr(evidence.document, "read_evidence_document", _read)
    r = client.post(URL, json={"file_ref": "attachments/x.pdf", "kind": "PRE_APPROVAL"})
    assert r.status_code == 200
    assert seen == {"file_ref": "attachments/x.pdf", "kind": "PRE_APPROVAL"}


def test_추출대상이_아닌_종류는_SKIPPED가_그대로_온다(monkeypatch):
    monkeypatch.setattr(evidence.document, "read_evidence_document", lambda ref, kind: {
        "file_ref": ref, "kind": kind, "extraction_status": "SKIPPED",
        "extracted": {}, "field_confidence": {}, "evidence_spans": [],
        "extractor_version": "v1", "warnings": ["추출 대상 종류가 아닙니다"],
    })
    body = client.post(URL, json={"file_ref": "a.pdf", "kind": "CONTRACT"}).json()
    assert body["extraction_status"] == "SKIPPED"
    assert body["extracted"] == {}


def test_판독_실패는_502다_빈_성공이_아니다(monkeypatch):
    monkeypatch.setattr(evidence.document, "read_evidence_document",
                        lambda ref, kind: (_ for _ in ()).throw(RuntimeError("vision down")))
    r = client.post(URL, json={"file_ref": "a.pdf", "kind": "PRE_APPROVAL"})
    assert r.status_code == 502
    assert "vision down" in r.json()["detail"]


def test_파일이_없으면_404(monkeypatch):
    monkeypatch.setattr(evidence.document, "read_evidence_document",
                        lambda ref, kind: (_ for _ in ()).throw(FileNotFoundError()))
    assert client.post(URL, json={"file_ref": "a.pdf", "kind": "PRE_APPROVAL"}).status_code == 404


def test_루트를_벗어나는_경로는_400으로_거부(monkeypatch):
    monkeypatch.setattr(evidence.document, "read_evidence_document",
                        lambda ref, kind: (_ for _ in ()).throw(UnsafeMediaPath("절대경로는 받지 않습니다")))
    r = client.post(URL, json={"file_ref": "/etc/passwd", "kind": "PRE_APPROVAL"})
    assert r.status_code == 400


@pytest.mark.parametrize("payload", [{}, {"file_ref": "  "}])
def test_file_ref가_비면_400(payload):
    assert client.post(URL, json=payload).status_code == 400
