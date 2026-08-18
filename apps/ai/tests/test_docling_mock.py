"""docling 모킹 회귀 — 파싱 대체가 하류(교정→청킹→조항)와 실제로 맞물리는지.

임베딩·Chroma는 부르지 않는다(과금·네트워크). 여기서 고정하는 계약은 넷이다:
  ① **꺼져 있는 게 기본** — env를 안 건드리면 운영 경로에 아무 영향이 없다.
  ② 덤프 `ParsedDoc`이 교정·청킹을 그대로 통과하고 **조항이 나온다**.
  ③ **이름이 안 맞으면 실패**한다 — 넘겨짚어 다른 문서를 적재하지 않는다.
  ④ 모킹으로 만든 결과는 **눈에 띈다**(경고 문구 + `dump:` doc_id).

덤프가 없는 환경(CI 등)에서는 통째로 skip한다 — 덤프는 레포에 있지만 경로가 다를 수 있다.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.dump_path import find_dump

from app.rag.parsing import mock

# 레포 루트/컨테이너 양쪽을 본다. 컨테이너는 `/data/docling_eval`로 마운트된다.
DUMP = find_dump()

pytestmark = pytest.mark.skipif(DUMP is None, reason="파싱 덤프가 없는 환경")


@pytest.fixture
def mocked(monkeypatch):
    monkeypatch.setenv("DOCLING_MOCK", "1")
    monkeypatch.setenv("DOCLING_MOCK_DUMP", str(DUMP))
    return mock


def test_disabled_by_default(monkeypatch):
    """스위치를 안 켜면 운영 경로가 그대로여야 한다 — 이게 이 기능의 안전 기본값이다."""
    monkeypatch.delenv("DOCLING_MOCK", raising=False)
    assert mock.enabled() is False
    for falsy in ("", "0", "false", "no"):
        monkeypatch.setenv("DOCLING_MOCK", falsy)
        assert mock.enabled() is False


def test_enabled_by_truthy_values(monkeypatch):
    for truthy in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("DOCLING_MOCK", truthy)
        assert mock.enabled() is True


def test_parse_returns_parsed_doc_and_a_loud_warning(mocked):
    doc, warning = mocked.parse("/uploads/법인카드_사용규정.pdf")
    assert doc.name == "법인카드_사용규정"
    assert doc.elements
    # 모킹 산출물은 Chroma에서도 실물과 구분돼야 한다(실물은 파일 해시).
    assert doc.doc_id.startswith("dump:")
    # 화면 배너로 뜰 문구 — 조용히 넘어가면 켜둔 걸 아무도 모른다.
    assert "모킹" in warning


def test_title_wins_over_filename(mocked):
    """업로드 제목이 있으면 그걸 먼저 본다(파일명은 임의로 바뀔 수 있다)."""
    doc, _ = mocked.parse("/uploads/무관한이름.pdf", name="출장비_사용규정")
    assert doc.name == "출장비_사용규정"


def test_unknown_name_fails_instead_of_guessing(mocked):
    """부분 일치로 넘겨짚으면 A 문서 내용이 B 레코드에 적재된다 — 그건 조용한 오염이다."""
    with pytest.raises(mock.MockDocumentNotFound) as exc:
        mocked.parse("/uploads/법인카드.pdf")          # '법인카드_사용규정'의 접두사
    # 실패 메시지가 고를 수 있는 이름을 알려줘야 사람이 바로 고친다.
    assert "법인카드_사용규정" in str(exc.value)


def test_downstream_chain_produces_clauses(mocked):
    """파싱 대체가 교정·청킹·조항 추출과 맞물리는지 — 이게 모킹의 존재 이유다."""
    from app.rag.chunking.chunker import chunk_document
    from app.rag.ingest import build_clauses
    from app.rag.parsing.corrections import pipeline

    doc, _ = mocked.parse("/uploads/법인카드_사용규정.pdf")
    pipeline.run(doc)
    chunks, _ = chunk_document(doc)
    clauses, _ = build_clauses(chunks)

    assert chunks, "청크가 하나도 안 나오면 하류를 시험할 수 없다"
    assert clauses, "조항이 안 나오면 규정 문서 화면이 빈 화면이 된다"
    first = clauses[0]
    assert first["articleLabel"].startswith("제")
    assert first["citation"].startswith("법인카드_사용규정 ")
    assert first["body"]


def test_law_profile_routes_to_tax_refs(mocked):
    """프로파일 판정도 덤프에서 그대로 나와야 컬렉션 라우팅이 운영과 같아진다."""
    from app.rag.embedding import store

    doc, _ = mocked.parse("/uploads/법인세법.pdf")
    assert doc.profile == "LAW"
    assert store.collection_for(doc.profile) == "tax_refs"
