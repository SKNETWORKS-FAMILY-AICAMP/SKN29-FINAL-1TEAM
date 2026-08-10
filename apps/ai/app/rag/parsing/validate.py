"""① PDF Validation — 파싱 전략 §13.1①, §10.2 케이스 1~3.

이후 단계가 예외를 만나지 않도록 여기서 열림/암호/손상을 확정한다.
파일 해시로 `document_id`를 확정해 동일 파일 재인덱싱 스킵 판별에 쓴다.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf


class PdfValidationError(Exception):
    """처리 불가 — 문서 단위 스킵 사유(암호/손상/빈 파일)."""


def document_id_of(data: bytes) -> str:
    """§9.1 `document_id` — 파일 해시 기반 안정 ID."""
    return hashlib.sha256(data).hexdigest()[:16]


def read_source(path: str | None = None, data: bytes | None = None) -> bytes:
    if data is not None:
        return data
    if not path:
        raise PdfValidationError("path 또는 data 중 하나는 필요합니다")
    p = Path(path)
    if not p.is_file():
        raise PdfValidationError(f"파일을 찾을 수 없습니다: {path}")
    return p.read_bytes()


def open_document(data: bytes, *, passwords: list[str] | None = None) -> tuple[pymupdf.Document, dict]:
    """PDF를 열고 검증 리포트를 반환한다.

    Fallback: 손상 → PyMuPDF 복구 모드는 open 시 자동 시도(`is_repaired`로 감지).
              암호 → 빈 암호·전달된 암호만 시도. **우회 시도 금지**(§10.2 케이스 2).
    """
    if not data:
        raise PdfValidationError("빈 파일")
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001
        raise PdfValidationError(f"열기 실패(손상 의심): {exc}") from exc

    if doc.needs_pass:
        for pw in ["", *(passwords or [])]:
            if doc.authenticate(pw):
                break
        else:
            doc.close()
            raise PdfValidationError("암호화된 문서 — 스킵(암호 우회 시도하지 않음)")

    if doc.page_count == 0:
        doc.close()
        raise PdfValidationError("페이지 0")

    report = {
        "pages": doc.page_count,
        "encrypted": bool(doc.needs_pass),
        "repaired": bool(getattr(doc, "is_repaired", False)),
        "size_bytes": len(data),
        # 추출 금지 권한이어도 소유자 암호 없이 열렸다면 진행한다(§10.2 케이스 3).
        "permissions": int(getattr(doc, "permissions", 0)),
    }
    return doc, report
