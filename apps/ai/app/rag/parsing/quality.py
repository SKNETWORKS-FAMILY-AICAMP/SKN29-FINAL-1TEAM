"""⑨ Quality Validation — 파싱 전략 §11, §13.1⑨.

**FAIL이면 인덱싱하지 않는다.** 나쁜 청크는 들어간 뒤에 지우기 어렵다.
조용한 실패가 RAG 품질 저하의 최대 원인이므로 지표를 항상 함께 반환한다.
"""
from __future__ import annotations

from app.rag.parsing.chunking import MIN_CHARS
from app.rag.parsing.metadata import missing_required
from app.rag.parsing.model import Chunk, DocElement, DocProfile, QualityReport

CHUNK_ANOMALY_LIMIT = 0.05      # §11.2 (<120자 or >최대) 청크 비율 목표


def evaluate(
    *,
    profile: DocProfile,
    elements: list[DocElement],
    chunks: list[Chunk],
    structure_info: dict,
    chunk_info: dict,
    boilerplate_removed_chars: int,
    raw_chars: int,
) -> QualityReport:
    report = QualityReport()
    kept_chars = sum(len(e.text) for e in elements) or 1

    nbsp = sum(e.text.count("\xa0") for e in elements)
    ctrl = sum(1 for e in elements for ch in e.text if ord(ch) < 32 and ch not in "\n\t")
    max_chars = chunk_info.get("max_chars", 1000)
    # 표 청크는 길이 이상 판정에서 제외한다 — "표 1개 = 청크 1개"가 §8.5의 명시 규칙이라
    # 짧거나 긴 것이 결함이 아니다. 대신 개수를 따로 보고한다.
    body_chunks = [
        c for c in chunks
        if c.metadata["element_type"] != "table" and not c.metadata.get("is_front_matter")
    ]
    anomalies = [
        c for c in body_chunks
        if c.metadata["char_len"] < MIN_CHARS or c.metadata["char_len"] > max_chars
    ]
    incomplete = [c.chunk_id for c in chunks if missing_required(c.metadata)]

    report.metrics = {
        "pages": profile.page_count,
        "elements": len(elements),
        "chunks": len(chunks),
        "tables": sum(1 for e in elements if e.type == "table"),
        "toc_anchor_rate": structure_info.get("toc_anchor_rate", 0.0),
        "structure_source": structure_info.get("structure_source"),
        "headings": structure_info.get("headings", 0),
        "nbsp_remaining": nbsp,
        "ctrl_chars_remaining": ctrl,
        "boilerplate_ratio": round(boilerplate_removed_chars / max(1, raw_chars), 4),
        "table_chunks": len(chunks) - len(body_chunks),
        "chunk_anomaly_ratio": round(len(anomalies) / len(body_chunks), 4) if body_chunks else 0.0,
        "meta_incomplete": len(incomplete),
        "target_chars": chunk_info.get("target_chars"),
        "avg_chunk_chars": round(sum(c.metadata["char_len"] for c in chunks) / len(chunks), 1) if chunks else 0,
    }

    # ── FAIL 조건: 인덱싱하면 안 되는 상태
    if not chunks:
        report.passed = False
        report.issues.append("청크 0개 — 인덱싱 불가")
    if incomplete:
        report.passed = False
        report.issues.append(f"필수 메타 결손 청크 {len(incomplete)}건 (목표 0)")
    if nbsp:
        report.passed = False
        report.issues.append(f"NBSP 잔존 {nbsp}자 — 정규화 실패(§6.1)")

    # ── 경고: 인덱싱은 가능하나 사람이 봐야 하는 상태
    if structure_info.get("structure_missing"):
        report.issues.append("구조 신호 3층 모두 실패 — structure_missing")
    elif structure_info.get("structure_source") != "toc":
        report.issues.append(f"구조 신호 폴백 사용: {structure_info.get('structure_source')}")
    if report.metrics["chunk_anomaly_ratio"] > CHUNK_ANOMALY_LIMIT:
        report.issues.append(
            f"청크 길이 이상 비율 {report.metrics['chunk_anomaly_ratio']:.2%} > {CHUNK_ANOMALY_LIMIT:.0%}"
        )
    return report
