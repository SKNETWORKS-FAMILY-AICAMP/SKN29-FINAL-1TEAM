"""규정 문서 업로드 → 인덱싱 실 HTTP E2E 테스트.

`docker compose up` 로 뜬 실제 서비스(core·ai·chroma)를 상대로 진짜 HTTP 요청을 보낸다.
Docling·FastAPI·Django·Chroma는 어느 모드에서도 mock하지 않는다 — 이 파일이 실제로
치는 건 그 서비스들이 **실제로 켜져 있을 때만** 의미가 있는 검증이기 때문이다(서비스가
없으면 각 테스트는 "실패"가 아니라 명시적 사유로 skip된다 — 이 스크립트 자체가 서비스를
띄우지는 않는다).

흐름(브라우저를 흉내낸다 — FastAPI는 내부 전용이라 사용자 트래픽은 항상 Django만 거친다,
CLAUDE.md §1):
    로그인(JWT) → POST /api/policy-docs/(PDF 업로드, 201) → Django가 내부적으로 FastAPI
    /embeddings/ingest(202)를 호출 → PolicyDoc.status를 폴링(PENDING→PARSING→INDEXING→
    DONE|FAILED) → DONE이면 Chroma에서 실제로 색인됐는지 확인.

**두 모드**:
  - 기본(CI) 모드: 업로드가 **접수**되는지(201, 상태가 PENDING/PARSING으로 전진하는지)까지만
    확인한다. 그 이상(임베딩 완료까지 폴링)은 ai 컨테이너의 실제 OpenAI 과금을 태우므로
    기본 모드에서는 확인하지 않는다 — "202만 보고 성공 처리하지 않는다"는 원칙은 지키되,
    실행 비용은 opt-in으로 미룬다.
  - `RUN_LIVE_RAG_E2E=1`: 완료까지 실제로 폴링하고, 실제 Chroma에서 색인 결과(고유 문구
    포함 여부)까지 확인한다. 실제 OpenAI 임베딩 호출이 발생한다(과금).
"""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import httpx
import pytest

CORE_BASE = os.environ.get("E2E_CORE_BASE_URL", "http://localhost:8080")
CHROMA_HOST = os.environ.get("E2E_CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.environ.get("E2E_CHROMA_PORT", "8001"))

E2E_USERNAME = os.environ.get("E2E_DJANGO_USERNAME", "acc")     # seed.py 기본 회계 계정
E2E_PASSWORD = os.environ.get("E2E_DJANGO_PASSWORD", "pass1234")

RUN_LIVE = os.environ.get("RUN_LIVE_RAG_E2E") == "1"
POLL_TIMEOUT_S = float(os.environ.get("E2E_POLL_TIMEOUT_S", "180"))
POLL_INTERVAL_S = 3.0

FIXTURE_PDF = Path(__file__).resolve().parents[1] / "fixtures" / "sample_regulation.pdf"
TERMINAL_STATUSES = {"DONE", "FAILED"}


def _core_reachable() -> tuple[bool, str]:
    try:
        resp = httpx.get(f"{CORE_BASE}/api/health/", timeout=3.0)
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    if resp.status_code != 200:
        return False, f"status={resp.status_code}"
    return True, ""


CORE_UP, CORE_DOWN_REASON = _core_reachable()

requires_live_stack = pytest.mark.skipif(
    not CORE_UP,
    reason=(
        f"Django(core)에 연결할 수 없다({CORE_DOWN_REASON}) — "
        f"`docker compose up`으로 스택을 띄우고 {CORE_BASE}로 접근 가능한지 확인할 것. "
        "이 테스트는 실행되지 않았다(실패가 아니라 미실행)."
    ),
)


@pytest.fixture(scope="module")
def auth_token() -> str:
    resp = httpx.post(
        f"{CORE_BASE}/api/auth/token/",
        json={"username": E2E_USERNAME, "password": E2E_PASSWORD},
        timeout=10.0,
    )
    assert resp.status_code == 200, (
        f"로그인 실패({resp.status_code}): {resp.text[:300]} — "
        f"seed 계정 `{E2E_USERNAME}`이 있는지 확인할 것(`docker compose exec core "
        "python manage.py seed`)"
    )
    token = resp.json().get("access")
    assert token, f"토큰 응답에 access 없음: {resp.text[:300]}"
    return token


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _upload(token: str, title: str) -> httpx.Response:
    with open(FIXTURE_PDF, "rb") as fh:
        return httpx.post(
            f"{CORE_BASE}/api/policy-docs/",
            headers=_auth_headers(token),
            files={"file": ("sample_regulation.pdf", fh, "application/pdf")},
            data={"title": title},
            timeout=30.0,
        )


def _get_doc(token: str, doc_id: int) -> dict:
    resp = httpx.get(
        f"{CORE_BASE}/api/policy-docs/{doc_id}/", headers=_auth_headers(token), timeout=10.0
    )
    resp.raise_for_status()
    return resp.json()


def _delete_doc(token: str, doc_id: int) -> None:
    try:
        httpx.delete(
            f"{CORE_BASE}/api/policy-docs/{doc_id}/", headers=_auth_headers(token), timeout=10.0
        )
    except Exception:  # noqa: BLE001 — 정리 실패로 테스트 자체를 실패시키지 않는다
        pass


@pytest.fixture
def uploaded_doc(auth_token):
    """업로드하고, 테스트가 끝나면 생성한 문서를 정리한다."""
    title = f"E2E 테스트 규정 {uuid.uuid4().hex[:8]}"
    resp = _upload(auth_token, title)
    doc_id = resp.json().get("id") if resp.status_code == 201 else None
    yield resp, title
    if doc_id is not None:
        _delete_doc(auth_token, doc_id)


# ── 1~4: health / 인증 / 업로드 접수(202/201) ────────────────────────────────

@requires_live_stack
def test_core_health():
    """1. 서비스 health check."""
    resp = httpx.get(f"{CORE_BASE}/api/health/", timeout=5.0)
    assert resp.status_code == 200


@requires_live_stack
def test_login_issues_jwt(auth_token):
    """2. Django 인증 준비 — 토큰이 실제로 발급된다."""
    assert isinstance(auth_token, str) and len(auth_token) > 20


@requires_live_stack
def test_upload_is_accepted_and_transitions_out_of_pending(uploaded_doc, auth_token):
    """3~7. 실제 PDF 업로드 → 201 → (Django가 내부적으로 FastAPI 202를 호출) →
    상태가 PENDING에 머무르지 않고 최소 PARSING 이상으로 전진하는지.

    **202만 보고 성공 처리하지 않는다**(§G) — 여기서는 "접수됐다"만 확인하고, 완료까지의
    폴링은 `RUN_LIVE_RAG_E2E=1`일 때만 한다(실제 임베딩 과금 때문).
    """
    resp, _title = uploaded_doc
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] in ("PENDING", "PARSING", "INDEXING", "DONE", "FAILED")
    doc_id = body["id"]

    # Django가 백그라운드로 ai를 부르는 데는 약간의 시차가 있다 — PENDING에 계속 머무르면
    # ai 호출(디스패치) 자체가 안 된 것이므로, 최소 하나는 전진해야 한다.
    deadline = time.monotonic() + 30
    last = body
    while time.monotonic() < deadline:
        last = _get_doc(auth_token, doc_id)
        if last["status"] != "PENDING":
            break
        time.sleep(1.0)
    assert last["status"] != "PENDING", (
        f"30초 안에 PENDING을 벗어나지 못했다 — ai 컨테이너가 안 떠 있거나 디스패치가 "
        f"실패했을 수 있다. 최종 상태: {last}"
    )


# ── live 모드: 완료까지 폴링 + 실제 색인 검증 (실제 OpenAI 과금) ─────────────

live = pytest.mark.skipif(
    not RUN_LIVE, reason="RUN_LIVE_RAG_E2E=1 이 아니면 실행하지 않는다(실제 OpenAI 임베딩 과금)"
)


@requires_live_stack
@live
def test_upload_reaches_done_and_is_searchable_in_chroma(uploaded_doc, auth_token):
    """6~11. 완료까지 폴링 → 최종 상태 DONE → 실제 Chroma에 색인됐는지 확인.

    (core에 `/clauses/` 같은 청크 전용 엔드포인트가 없어 §F-9는 PolicyDoc의
    `chunkCount`/`leafCount`로 대체 확인한다. §F-10~11의 "검색"은 공개 검색 API가 없어
    Chroma를 직접 메타데이터로 조회해 fixture 고유 문구가 실제로 들어갔는지 본다 —
    관리자 AI-LAB의 RAG 검색 탭이 쓰는 것과 같은 하부 스토어다.)
    """
    resp, title = uploaded_doc
    doc_id = resp.json()["id"]

    deadline = time.monotonic() + POLL_TIMEOUT_S
    final = _get_doc(auth_token, doc_id)
    while final["status"] not in TERMINAL_STATUSES and time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL_S)
        final = _get_doc(auth_token, doc_id)

    assert final["status"] in TERMINAL_STATUSES, (
        f"{POLL_TIMEOUT_S}초 안에 끝나지 않았다(마지막 상태 {final['status']}) — "
        f"ai 컨테이너 로그를 확인할 것. 최종 응답: {final}"
    )
    assert final["status"] == "DONE", f"적재 실패: {final.get('error')}"
    assert final["chunkCount"] > 0
    assert final["leafCount"] > 0
    assert final["collection"]

    import chromadb

    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    collection = client.get_or_create_collection(final["collection"])
    got = collection.get(where={"doc_name": title}, include=["documents"])
    assert got["documents"], f"Chroma `{final['collection']}`에서 doc_name={title!r} 청크를 못 찾았다"
    joined = " ".join(got["documents"])
    assert "sample provisions for testing" in joined, (
        "fixture 고유 문구가 색인된 문서 내용에 없다 — 파싱·청킹이 내용을 유실했을 수 있다"
    )


# ── G: 실패 상태 전달 검증 ───────────────────────────────────────────────────

@requires_live_stack
def test_non_pdf_upload_is_rejected_before_any_ingest(auth_token):
    """비-PDF는 core 단에서 즉시 거절돼야 한다 — ai를 부르지도 않는다(§ 회귀 기준
    `apps/core/domain/policies/tests/test_policy_docs.py::test_non_pdf_is_rejected_before_dispatch`
    와 같은 계약을 실 HTTP로 재확인)."""
    resp = httpx.post(
        f"{CORE_BASE}/api/policy-docs/",
        headers=_auth_headers(auth_token),
        files={"file": ("규정.docx", b"not a pdf", "application/msword")},
        timeout=10.0,
    )
    assert resp.status_code == 400


@requires_live_stack
def test_anonymous_upload_is_rejected():
    """인가 없이는 업로드도, 상태 조회도 못 한다."""
    resp = httpx.post(
        f"{CORE_BASE}/api/policy-docs/",
        files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")},
        timeout=10.0,
    )
    assert resp.status_code == 403
