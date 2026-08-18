"""RAG 적재 파이프라인(`ingest_pdf`) 통합 테스트 — 실제 PDF, 실제 Chroma(로컬 영속),
가짜 OpenAI 클라이언트.

**Docling PDF 변환은 mock하지 않는다** — 실제 `engine.convert()`가 fixture PDF를 실제로
파싱한다. OpenAI·Chroma만 테스트 대역을 쓴다:
  - OpenAI: `openai.OpenAI`를 결정론적 가짜 클라이언트로 치환(네트워크·과금 없음).
  - Chroma: `chromadb.PersistentClient`(진짜 라이브러리, `tmp_path` 로컬 디렉터리) —
    HTTP로 뜬 chroma 컨테이너가 없어도 실제 upsert/count/get을 검증할 수 있다.
    `store.get_client()`가 `settings.chroma_persist_dir`이 설정되면 이 경로를 쓰도록
    이미 설계돼 있다(§ store.py 문서화 — "docker 없이 인덱싱·검증을 돌리기 위한 경로").
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api import embeddings as embeddings_api
from app.config import settings
from app.rag import ingest as ingest_mod
from app.rag.embedding import store

from tests.rag.conftest import SAMPLE_PDF, requires_docling


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    @property
    def total_inputs(self) -> int:
        return sum(len(c) for c in self.calls)


class _FakeEmbeddings:
    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder

    def create(self, model, input, dimensions):  # noqa: A002 - openai SDK 시그니처를 따른다
        batch = list(input)
        self._recorder.calls.append(batch)
        data = [
            SimpleNamespace(index=i, embedding=[1.0 + i * 0.001] * dimensions)
            for i in range(len(batch))
        ]
        return SimpleNamespace(data=data, usage=SimpleNamespace(prompt_tokens=len(batch) * 3))


class _FakeOpenAIClient:
    def __init__(self, recorder: _Recorder, *_a, **_kw) -> None:
        self.embeddings = _FakeEmbeddings(recorder)


@pytest.fixture
def fake_openai(monkeypatch) -> _Recorder:
    """`OpenAIEncoder.client`가 지연 생성하는 `openai.OpenAI(...)`를 가짜로 치환.

    실제 API 키가 없어도(그리고 있어도) 네트워크를 타지 않는다 — `settings.openai_api_key`만
    비어 있지 않으면 되므로 더미 값을 채운다(진짜 키가 아니어도 가짜 클라이언트는 그 값을
    쓰지 않는다).
    """
    recorder = _Recorder()
    monkeypatch.setattr(settings, "openai_api_key", "test-dummy-key")
    monkeypatch.setattr("openai.OpenAI", lambda *a, **kw: _FakeOpenAIClient(recorder, *a, **kw))
    return recorder


@pytest.fixture
def local_chroma(monkeypatch, tmp_path):
    """`store.get_client()`가 HTTP 대신 `tmp_path`의 진짜 PersistentClient를 쓰게 한다."""
    persist_dir = tmp_path / "chroma"
    persist_dir.mkdir()
    monkeypatch.setattr(settings, "chroma_persist_dir", str(persist_dir))
    return persist_dir


@pytest.fixture
def captured_chunks(monkeypatch):
    """`ingest.py`가 부르는 `store.upsert_chunks`를 가로채 실제 Chunk 목록을 기록하되,
    호출 자체는 진짜 구현(가짜 인코더·로컬 Chroma 경유)으로 위임한다."""
    captured: list = []
    real_upsert = store.upsert_chunks

    def spy(chunks, profile_of, **kw):
        chunks = list(chunks)
        captured.append(chunks)
        return real_upsert(chunks, profile_of, **kw)

    monkeypatch.setattr(ingest_mod.store, "upsert_chunks", spy)
    return captured


# ── ingest_pdf 성공 경로 ─────────────────────────────────────────────────────

@requires_docling
def test_ingest_pdf_success_end_to_end(fake_openai, local_chroma, captured_chunks):
    result = ingest_mod.ingest_pdf(SAMPLE_PDF)

    # 1. 파싱 성공
    assert result.ok, result.error
    # 2. 문서 ID 유지 — 파일 내용 해시와 일치
    from app.rag.parsing.engine import doc_id_of

    assert result.doc_id == doc_id_of(SAMPLE_PDF)
    # 3. 청크 1개 이상 생성
    assert result.chunk_count >= 1

    assert len(captured_chunks) == 1
    chunks = captured_chunks[0]
    assert len(chunks) == result.chunk_count

    for chunk in chunks:
        # 4. 각 청크 text가 비어 있지 않음
        assert chunk.text.strip(), f"빈 텍스트 청크: {chunk.chunk_id}"
        # 5. 필수 metadata — doc_id로 원본 문서와 연결(policyDocId는 core 쪽 개념이라
        #    ingest_pdf 경계 밖이다 — app/api/embeddings.py의 IngestRequest.policyDocId가
        #    그 연결을 맡는다. 여기서는 doc_id 연결만 검증한다).
        assert chunk.doc_id == result.doc_id
        # 7. citation·page metadata 존재
        assert chunk.citation
        assert chunk.page_start == 1 and chunk.page_end == 1  # fixture가 1페이지

    # 6. chunk id 유일성 + 순서(atomic/child 체인의 prev/next 연결) 정상
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids)), "chunk_id 중복"
    chain = [c for c in chunks if c.chunk_role != "parent"]
    for prev, nxt in zip(chain, chain[1:]):
        assert prev.next_chunk_id == nxt.chunk_id
        assert nxt.prev_chunk_id == prev.chunk_id

    # 8. 임베딩 호출: 입력 총량이 upsert된 청크 수(=이 컬렉션의 전체 청크 수)와 같아야 한다
    assert fake_openai.total_inputs == len(chunks)
    assert len(fake_openai.calls) >= 1

    # 9. Chroma upsert 개수와 생성 청크 개수 일치 — 실제 Chroma에 되물어 확인
    import chromadb

    client = chromadb.PersistentClient(path=str(local_chroma))
    collection = client.get_or_create_collection(result.collection)
    assert collection.count() == result.chunk_count == len(chunks)


@requires_docling
def test_reingesting_same_document_is_idempotent(fake_openai, local_chroma):
    """같은 파일을 두 번 적재해도 Chroma 건수가 늘지 않는다 — doc_id가 파일 해시라
    chunk_id가 그대로 재생성되고, upsert가 같은 ID를 덮어쓴다(§ ingest.py docstring)."""
    first = ingest_mod.ingest_pdf(SAMPLE_PDF)
    assert first.ok
    second = ingest_mod.ingest_pdf(SAMPLE_PDF)
    assert second.ok

    assert first.doc_id == second.doc_id
    assert first.chunk_count == second.chunk_count

    import chromadb

    client = chromadb.PersistentClient(path=str(local_chroma))
    collection = client.get_or_create_collection(second.collection)
    assert collection.count() == second.chunk_count, "재적재로 건수가 중복 누적됐다"


# ── 파싱 실패 경로 ────────────────────────────────────────────────────────

def test_parse_failure_returns_error_and_never_touches_embedding_or_chroma(
    fake_openai, local_chroma, tmp_path, monkeypatch
):
    """유효하지 않은 PDF(진짜 손상 파일) — mock으로 실패를 흉내내지 않고 실제로
    docling이 실패하는 입력을 준다."""
    bad_pdf = tmp_path / "not_a_real.pdf"
    bad_pdf.write_bytes(b"%PDF-1.4\nthis is not a valid pdf body at all")

    def _fail_if_called(*_a, **_kw):
        raise AssertionError("파싱 실패 시 upsert_chunks가 호출되면 안 된다")

    monkeypatch.setattr(ingest_mod.store, "upsert_chunks", _fail_if_called)

    result = ingest_mod.ingest_pdf(bad_pdf)

    assert result.ok is False
    assert result.error
    assert fake_openai.calls == [], "파싱 실패 시 임베딩 호출이 없어야 한다"


# ── 백그라운드 태스크(app/api/embeddings.py::_run) 상태 전이 ────────────────

class _ReportRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, method, path, json=None, **_kw):  # noqa: A002
        self.calls.append((method, path, json or {}))
        return SimpleNamespace(status_code=200, json=lambda: {})


@pytest.fixture
def report_spy(monkeypatch) -> _ReportRecorder:
    recorder = _ReportRecorder()
    monkeypatch.setattr(embeddings_api.core_auth, "request", recorder)
    return recorder


@requires_docling
def test_background_run_reports_parsing_then_done(
    fake_openai, local_chroma, report_spy, monkeypatch
):
    monkeypatch.setattr(embeddings_api, "MEDIA_ROOT", SAMPLE_PDF.parent)
    req = embeddings_api.IngestRequest(policyDocId=1, filePath=SAMPLE_PDF.name)

    embeddings_api._run(req)

    statuses = [c[2].get("status") for c in report_spy.calls]
    assert statuses[0] == "PARSING"
    assert statuses[-1] == "DONE"
    assert "FAILED" not in statuses
    done_payload = report_spy.calls[-1][2]
    assert done_payload["chunkCount"] > 0
    assert done_payload["docId"]


def test_background_run_reports_parsing_then_failed_on_parse_error(
    fake_openai, local_chroma, report_spy, monkeypatch, tmp_path
):
    bad_pdf = tmp_path / "broken.pdf"
    bad_pdf.write_bytes(b"not a pdf")
    monkeypatch.setattr(embeddings_api, "MEDIA_ROOT", tmp_path)
    req = embeddings_api.IngestRequest(policyDocId=2, filePath=bad_pdf.name)

    embeddings_api._run(req)

    statuses = [c[2].get("status") for c in report_spy.calls]
    assert statuses[0] == "PARSING"
    assert statuses[-1] == "FAILED"
    failed_payload = report_spy.calls[-1][2]
    assert failed_payload["error"]  # 사용자에게 보여줄 오류 메시지가 채워져 있어야 한다


@requires_docling
def test_retry_after_failure_succeeds_without_duplicate_growth(
    fake_openai, local_chroma, report_spy, monkeypatch, tmp_path
):
    """실패 후 같은 policyDocId로 재시도하면(운영에서는 "재색인" 버튼) 정상 적재되고,
    Chroma에 중복이 쌓이지 않는다."""
    bad_pdf = tmp_path / "broken.pdf"
    bad_pdf.write_bytes(b"not a pdf")
    monkeypatch.setattr(embeddings_api, "MEDIA_ROOT", tmp_path)

    embeddings_api._run(embeddings_api.IngestRequest(policyDocId=3, filePath=bad_pdf.name))
    assert report_spy.calls[-1][2]["status"] == "FAILED"

    monkeypatch.setattr(embeddings_api, "MEDIA_ROOT", SAMPLE_PDF.parent)
    embeddings_api._run(embeddings_api.IngestRequest(policyDocId=3, filePath=SAMPLE_PDF.name))
    assert report_spy.calls[-1][2]["status"] == "DONE"

    import chromadb

    client = chromadb.PersistentClient(path=str(local_chroma))
    done_payload = report_spy.calls[-1][2]
    collection = client.get_or_create_collection(done_payload["collection"])
    assert collection.count() == done_payload["chunkCount"]
