"""docling 변환 — `pdf_parsing_strategy.md` §2.1.

설정은 `docling_eval/docling_parsing_test.ipynb`에서 11종 전건 SUCCESS를 확인한 값을
그대로 옮긴 것이다. 임의로 바꾸지 말 것 — 바꾸면 평가 노트북의 채점 기준(Overall 89.3)과
런타임 파싱이 어긋난다.

⚠️ `TORCHDYNAMO_DISABLE`은 torch/docling import보다 **먼저** 설정돼야 한다.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")   # noqa: E402 — import 순서가 의미를 가진다

from app.rag.parsing import profile as profile_mod
from app.rag.parsing.model import Element, ElementType, ParseReport, ParsedDoc

# docling 라벨 → CDM 요소 타입. 하류는 docling 라벨을 모른다.
_LABEL_MAP: dict[str, ElementType] = {
    "title": "title",
    "section_header": "heading",
    "text": "paragraph",
    "list_item": "list_item",
    "table": "table",
    "picture": "figure",
    "caption": "caption",
    "footnote": "footnote",
    "code": "code_block",
    "formula": "paragraph",
    "page_header": "header",
    "page_footer": "footer",
}


def _build_converter():
    """모델 로딩이 비싸므로 호출부에서 재사용할 것 (문서마다 만들지 않는다)."""
    from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions()
    opts.do_table_structure = True
    opts.table_structure_options.do_cell_matching = True
    opts.do_ocr = False                                 # 텍스트 레이어 존재(11종 확인)
    opts.heading_hierarchy_options.enabled = True       # 계층 복원의 핵심 스위치

    fmt = PdfFormatOption(pipeline_options=opts)
    fmt.backend = PyPdfiumDocumentBackend
    primary = DocumentConverter(format_options={InputFormat.PDF: fmt})
    # 백엔드 2단 폴백 — pypdfium2 실패 시 docling-parse 기본 백엔드
    fallback = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )
    return primary, fallback


def doc_id_of(path: Path) -> str:
    """파일 해시 기반 안정 ID — 동일 파일 재인덱싱 스킵 판별에 쓴다."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def convert(pdf_path: str | Path, converters=None) -> ParsedDoc:
    """PDF → 교정 **이전** 상태의 `ParsedDoc`. 교정은 `corrections.pipeline`이 건다."""
    from docling.datamodel.base_models import ConversionStatus

    path = Path(pdf_path)
    primary, fallback = converters or _build_converter()
    report = ParseReport()

    result = None
    for label, conv in (("pypdfium2", primary), ("docling-parse", fallback)):
        try:
            res = conv.convert(path)
        except Exception as exc:  # noqa: BLE001 — 백엔드별 예외를 모아 폴백한다
            report.warnings.append(f"{label}: {type(exc).__name__}: {exc}"[:200])
            continue
        if res.status in (ConversionStatus.SUCCESS, ConversionStatus.PARTIAL_SUCCESS):
            result, used = res, label
            break
        report.warnings.append(f"{label}: status={res.status.value}")
    if result is None:
        raise RuntimeError(f"docling 변환 실패: {path.name} — {report.warnings}")

    if used != "pypdfium2":
        report.warnings.append(f"1순위 백엔드 실패 → {used} 로 폴백")

    doc_id = doc_id_of(path)
    elements = list(_to_elements(result.document, doc_id))
    parsed = ParsedDoc(
        doc_id=doc_id,
        name=path.stem,
        profile=profile_mod.detect(elements),
        elements=elements,
        report=report,
    )
    parsed.report.profile = parsed.profile
    return parsed


def _to_elements(document, doc_id: str):
    """DoclingDocument → Element[]. 여기가 엔진 이질성이 끊기는 유일한 지점이다."""
    from docling_core.types.doc import DocItemLabel

    for seq, (item, level) in enumerate(document.iterate_items()):
        label = getattr(getattr(item, "label", None), "value", None) or str(
            getattr(item, "label", "")
        )
        etype = _LABEL_MAP.get(label)
        if etype is None:
            continue

        prov = (getattr(item, "prov", None) or [None])[0]
        page = getattr(prov, "page_no", 0) or 0
        bbox = None
        if prov is not None and getattr(prov, "bbox", None) is not None:
            b = prov.bbox
            bbox = (b.l, b.t, b.r, b.b)

        attrs: dict = {}
        if etype == "table":
            text, attrs = _table_payload(item)
        else:
            text = (getattr(item, "text", "") or "").strip()
            if not text:
                continue

        el = Element(
            element_id=f"{doc_id}:p{page}:e{seq}",
            type=etype,
            text=text,
            page=page,
            order=seq,
            level=level if label == DocItemLabel.SECTION_HEADER.value else None,
            bbox=bbox,
            attrs=attrs,
        )
        yield el


def _table_payload(item) -> tuple[str, dict]:
    """표는 이중 저장 — Markdown(임베딩·LLM용) + grid(정확 값 조회용).

    룰 임계값의 원천이 되는 한도표는 grid로 읽는다. 실측 셀 정확도 0.965는 grid 기준.
    """
    grid: list[list[str]] = []
    data = getattr(item, "data", None)
    for row in (getattr(data, "grid", None) or []):
        grid.append([(getattr(c, "text", "") or "").strip() for c in row])

    md = ""
    try:
        md = item.export_to_markdown()
    except Exception:  # noqa: BLE001 — 직렬화 실패해도 grid는 살린다
        if grid:
            md = "\n".join(" | ".join(r) for r in grid)

    return md or f"<table {len(grid)}x{len(grid[0]) if grid else 0}>", {
        "rows": len(grid),
        "cols": len(grid[0]) if grid else 0,
        "grid": grid,
        "header_row": grid[0] if grid else [],
        "header_rows": 1 if grid else 0,     # 청킹의 행 분할이 반복할 헤더 행 수
    }
