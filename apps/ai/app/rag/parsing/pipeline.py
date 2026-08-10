"""PDF 파싱·청킹 파이프라인 오케스트레이션 — 파싱 전략 §13.

Validation → Profiling → Parser Selection → Extraction → CDM →
Normalization(§6.12 순서 준수) → Structure → Metadata → Quality → Chunking

임베딩·Chroma upsert(§13.1⑪⑫)는 이 모듈 범위 밖이다. 여기까지가 "청킹"이다.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any

import pdfplumber

from app.rag.parsing import normalize as N
from app.rag.parsing.chunking import chunk_document
from app.rag.parsing.model import DocElement, ParseResult
from app.rag.parsing.parsers import layout as layout_parser
from app.rag.parsing.parsers import ocr as ocr_parser
from app.rag.parsing.parsers import tables as table_parser
from app.rag.parsing.parsers.base import ParserUnavailable
from app.rag.parsing.profile import profile_document
from app.rag.parsing.quality import evaluate
from app.rag.parsing.router import PARSER_REGISTRY, register, select_parsers
from app.rag.parsing.structure import build_tree
from app.rag.parsing.validate import document_id_of, open_document, read_source

log = logging.getLogger(__name__)

register(layout_parser.parser)
register(table_parser.parser)
register(ocr_parser.parser)

MAX_FALLBACKS = 2      # §10.1 — Fallback 시도 상한: 문서당 2회


def parse_pdf(
    *,
    path: str | None = None,
    data: bytes | None = None,
    filename: str | None = None,
    document_type: str = "regulation",
    target_chars: int | None = None,
    max_chars: int | None = None,
) -> ParseResult:
    raw = read_source(path, data)
    document_id = document_id_of(raw)
    source_path = path or (filename or "<upload>")
    doc, _report = open_document(raw)
    quarantine: list[dict[str, Any]] = []

    try:
        profile = profile_document(
            doc,
            document_id=document_id,
            source_path=source_path,
            document_name=Path(filename or source_path).stem,
        )
        ctx = {"document_id": document_id, "body_size": profile.body_size}
        elements: list[DocElement] = []

        with pdfplumber.open(io.BytesIO(raw)) as plumber:
            for page_profile in profile.pages:
                page = doc[page_profile.page_no - 1]

                if page_profile.is_duplicate:                 # §10.2 케이스 14
                    quarantine.append(_q(document_id, page_profile.page_no, "profile", "duplicate page", "skipped"))
                    continue
                if page_profile.char_count < 50 and page_profile.image_area_ratio <= 0.03:
                    continue                                  # §10.2 케이스 13 — 빈 페이지

                selected = select_parsers(page_profile)
                page_elements: list[DocElement] = []

                # 표를 먼저 추출하고 그 bbox를 텍스트 흐름에서 제외한다(§6.12 2번).
                table_elements: list[DocElement] = []
                if "table" in selected:
                    try:
                        table_elements = PARSER_REGISTRY["table"].parse(
                            plumber.pages[page_profile.page_no - 1], page_profile, ctx
                        )
                    except Exception as exc:  # noqa: BLE001
                        quarantine.append(
                            _q(document_id, page_profile.page_no, "table_extract", str(exc), "kept_as_paragraph")
                        )
                page_elements.extend(table_elements)

                if "ocr" in selected:
                    try:
                        page_elements.extend(
                            PARSER_REGISTRY["ocr"].parse(page, page_profile, ctx)
                        )
                        selected = [s for s in selected if s != "layout"]
                    except ParserUnavailable as exc:
                        quarantine.append(
                            _q(document_id, page_profile.page_no, "ocr", str(exc), "fallback_to_layout")
                        )

                if "layout" in selected or not page_elements:
                    page_elements.extend(
                        PARSER_REGISTRY["layout"].parse(
                            page,
                            page_profile,
                            {**ctx, "exclude_bboxes": [
                                (t.bbox.x0, t.bbox.y0, t.bbox.x1, t.bbox.y1) for t in table_elements
                            ]},
                        )
                    )

                page_elements.sort(key=lambda e: (round(e.bbox.y0, 1), e.bbox.x0))
                elements.extend(page_elements)
    finally:
        doc.close()

    for order, el in enumerate(elements):
        el.order = order

    raw_chars = sum(len(e.text) for e in elements)
    page_heights = {p.page_no: p.height for p in profile.pages}

    # ── §6.12 전처리 실행 순서 (순서 의존성 있음)
    #    1. 유니코드 정규화는 파서에서 이미 적용됨(code_block 예외 포함)
    #    2. 표 영역 제외도 위에서 완료
    #    3. 헤더/푸터/페이지번호 판정 및 제거 — 문서번호는 메타로 승격
    sigs = N.detect_boilerplate(
        elements, n_pages=profile.page_count, body_size=profile.body_size, page_heights=page_heights
    )
    kept, removed, guard_tripped = N.strip_boilerplate(elements, sigs)
    if guard_tripped:
        quarantine.append(_q(document_id, 0, "boilerplate", "제거량 25% 초과", "removal_skipped"))
    doc_meta = N.extract_doc_meta(removed, kept)

    # 4. 각주 분리 → 5. 문단 경계 복원 → 6. 페이지 간 병합(3번 이후여야 발동)
    N.classify_footnotes(kept, page_heights, profile.body_size)
    kept = N.merge_lines_to_paragraphs(kept)
    kept = N.merge_across_pages(kept)
    kept = table_parser.merge_split_tables(kept)      # §7.1.4 분할 표 병합
    for order, el in enumerate(kept):
        el.order = order

    root, structure_info = build_tree(
        kept,
        document_id=document_id,
        document_title=profile.document_name,
        toc=profile.toc,
        body_size=profile.body_size,
    )

    chunks, parents, chunk_info = chunk_document(
        root,
        document_id=document_id,
        document_name=profile.document_name,
        document_type=document_type,
        source_path=source_path,
        doc_meta=doc_meta,
        target=target_chars,
        max_chars=max_chars,
    )

    quality = evaluate(
        profile=profile,
        elements=kept,
        chunks=chunks,
        structure_info=structure_info,
        chunk_info=chunk_info,
        boilerplate_removed_chars=sum(len(e.text) for e in removed),
        raw_chars=raw_chars,
    )
    structure_info.update(chunk_info)

    return ParseResult(
        profile=profile,
        doc_meta=doc_meta,
        elements=kept,
        root=root,
        chunks=chunks,
        parents=parents,
        quality=quality,
        quarantine=quarantine,
        structure_info=structure_info,
    )


def _q(document_id: str, page: int, stage: str, error: str, action: str) -> dict[str, Any]:
    """§10.3 격리 레코드 — 실패한 문서·페이지는 삭제하지 않고 기록한다."""
    return {
        "document_id": document_id,
        "page": page,
        "stage": stage,
        "error": error,
        "action_taken": action,
    }
