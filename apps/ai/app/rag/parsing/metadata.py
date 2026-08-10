"""⑧ Metadata Enrichment — 파싱 전략 §9, §13.1⑧.

**Chroma metadata는 스칼라(str/int/float/bool)만 허용**한다.
리스트·dict는 여기서 문자열로 직렬화한다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.rag.parsing.model import PIPELINE_VERSION

REQUIRED_FIELDS = (
    "document_id", "document_name", "document_type", "chunk_id", "parent_id",
    "element_type", "page_start", "page_end", "section_path", "section",
    "heading_level", "order", "char_len", "source_path", "parser",
    "parse_confidence", "ingested_at", "pipeline_version",
)


def scalarize(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return ",".join(str(v) for v in value)
    return str(value)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_metadata(
    *,
    document_id: str,
    document_name: str,
    document_type: str,
    source_path: str,
    doc_meta: dict[str, Any],
    chunk_id: str,
    parent_id: str,
    element_type: str,
    page_start: int,
    page_end: int,
    section_path: str,
    section: str,
    subsection: str = "",
    article_no: int | None = None,
    heading_level: int = 1,
    order: int = 0,
    char_len: int = 0,
    parser: str = "layout",
    parse_confidence: float = 1.0,
    ingested_at: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "document_id": document_id,
        "document_name": document_name,
        "document_type": document_type,
        "chunk_id": chunk_id,
        "parent_id": parent_id,
        "element_type": element_type,
        "page_start": page_start,
        "page_end": page_end,
        "section_path": section_path,
        "section": section,
        "heading_level": heading_level,
        "order": order,
        "char_len": char_len,
        "source_path": source_path,
        "parser": parser,
        "parse_confidence": round(float(parse_confidence), 3),
        "ingested_at": ingested_at or now_iso(),
        "pipeline_version": PIPELINE_VERSION,
    }
    if subsection:
        meta["subsection"] = subsection
    if article_no is not None:
        meta["article_no"] = article_no                 # 범위 검색(제9~11조)
    for key in ("doc_no", "doc_version", "effective_date"):   # 조건부(규정) — 개정 추적
        if doc_meta.get(key):
            meta[key] = doc_meta[key]
    for key, value in (extra or {}).items():
        if value is None or value == "" or value == []:
            continue
        meta[key] = scalarize(value)
    return meta


def missing_required(meta: dict[str, Any]) -> list[str]:
    """§11.2 메타데이터 누락률 목표 0.00 — 결손은 검증 단계에서 차단한다."""
    return [f for f in REQUIRED_FIELDS if f not in meta or meta[f] == ""]
