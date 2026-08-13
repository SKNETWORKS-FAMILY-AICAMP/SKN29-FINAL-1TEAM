"""docling 산출물 덤프 → `ParsedDoc` 로더 (검증 전용 경로).

`docling_eval/output/layout/layout_result.csv`는 11종 4,388개 요소 전량을 라벨·레벨·bbox·
원문까지 담은 덤프다. 이 로더가 있으면 **docling 재실행 없이 교정 계층을 실데이터로 회귀
검증**할 수 있다(docling은 별도 conda 환경을 요구하고 모델 로딩이 비싸다).

⚠️ 운영 인덱싱 경로가 아니다. 운영은 `engine.convert()`를 쓴다. 이 모듈은
`apps/ai/tests/`와 관리자 검증 배치에서만 import한다.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from app.rag.parsing import profile as profile_mod
from app.rag.parsing.model import Element, ElementType, ParseReport, ParsedDoc

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

_TYPE_MAP: dict[str, ElementType] = {
    "Heading": "heading",
    "Title": "title",
    "Text": "paragraph",
    "List": "list_item",
    "Table": "table",
    "Picture": "figure",
    "Caption": "caption",
    "Footnote": "footnote",
    "Code": "code_block",
    "Formula": "paragraph",
    "Header": "header",
    "Footer": "footer",
}


def _bbox(raw: str) -> tuple[float, float, float, float] | None:
    parts = raw.split(",")
    if len(parts) != 4:
        return None
    try:
        return tuple(float(p) for p in parts)  # type: ignore[return-value]
    except ValueError:
        return None


def _level(raw: str) -> int | None:
    """'H1' → 1. 덤프의 Level 컬럼은 헤딩에만 채워져 있다."""
    raw = (raw or "").strip()
    return int(raw[1:]) if raw.startswith("H") and raw[1:].isdigit() else None


def load_all(layout_csv: str | Path, tables_dir: str | Path | None = None) -> dict[str, ParsedDoc]:
    """덤프 CSV 한 개에서 문서별 `ParsedDoc`을 만든다."""
    # 덤프는 레포 루트(`docling_eval/`)에 있고 컨테이너에는 `/data/docling_eval`로 마운트된다.
    # 맨 FileNotFoundError만 던지면 "상대경로가 틀렸나?"로 헤매게 되므로 어디를 보라고 알려준다.
    if not Path(layout_csv).is_file():
        raise FileNotFoundError(
            f"파싱 덤프를 찾지 못했다: {layout_csv}\n"
            "  · 호스트에서 실행: --dump docling_eval/output (레포 루트 기준)\n"
            "  · ai 컨테이너에서 실행: --dump /data/docling_eval/output\n"
            "    (compose가 `./docling_eval:/data/docling_eval:ro`로 마운트한다. "
            "마운트를 추가한 뒤에는 `docker compose up -d ai`로 컨테이너를 다시 만들어야 반영된다)"
        )
    rows_by_doc: dict[str, list[dict]] = {}
    with open(layout_csv, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            rows_by_doc.setdefault(row["Document"], []).append(row)

    docs: dict[str, ParsedDoc] = {}
    for name, rows in rows_by_doc.items():
        rows.sort(key=lambda r: int(r["Order"]))
        elements: list[Element] = []
        for row in rows:
            etype = _TYPE_MAP.get(row["Element Type"])
            if etype is None:
                continue
            page = int(row["Page"] or 0)
            order = int(row["Order"])
            elements.append(
                Element(
                    element_id=f"{name}:p{page}:e{order}",
                    type=etype,
                    text=row["Text"],
                    page=page,
                    order=order,
                    level=_level(row["Level"]),
                    bbox=_bbox(row["BBox (l,t,r,b)"]),
                )
            )
        if tables_dir:
            _attach_grids(name, elements, Path(tables_dir) / name)

        doc = ParsedDoc(
            doc_id=f"dump:{name}",
            name=name,
            profile=profile_mod.detect(elements),
            elements=elements,
            report=ParseReport(),
            parser_version="docling-dump",
        )
        doc.report.profile = doc.profile
        docs[name] = doc
    return docs


def _to_matrix(cells: list[dict]) -> tuple[list[list[str]], int]:
    """셀 레코드 평면 배열 → 행렬 + 헤더 행 수.

    덤프 JSON의 `cells`는 `{row, col, row_span, col_span, column_header, text}` 레코드
    **목록**이다. 반면 운영 경로(`engine._table_payload`)의 `grid`는 `list[list[str]]`
    이다. 두 경로가 같은 계약을 내놓지 않으면 교정·청킹이 덤프에서만 조용히 어긋난다
    (실제로 C5가 셀 dict를 행으로 착각해 병합 표 텍스트를 `row | col | …`로 만들었다).
    """
    if not cells:
        return [], 0
    nrows = max(c["row"] + c.get("row_span", 1) for c in cells)
    ncols = max(c["col"] + c.get("col_span", 1) for c in cells)
    matrix = [["" for _ in range(ncols)] for _ in range(nrows)]
    header_rows = 0
    for cell in cells:
        text = (cell.get("text") or "").strip()
        for dr in range(cell.get("row_span", 1)):
            for dc in range(cell.get("col_span", 1)):
                matrix[cell["row"] + dr][cell["col"] + dc] = text
        if cell.get("column_header"):
            header_rows = max(header_rows, cell["row"] + cell.get("row_span", 1))
    return matrix, header_rows or 1


def _attach_grids(name: str, elements: list[Element], table_dir: Path) -> None:
    """덤프 CSV의 표는 `<table RxC>` 자리표시자라 셀 격자를 JSON에서 붙여 준다."""
    if not table_dir.is_dir():
        return
    files = sorted(table_dir.glob("table_*.json"))
    tables = [e for e in elements if e.type == "table"]
    for el, path in zip(tables, files):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        grid, header_rows = _to_matrix(payload.get("cells") or [])
        el.attrs.update(
            {
                "rows": len(grid),
                "cols": len(grid[0]) if grid else 0,
                "grid": grid,
                "header_row": grid[0] if grid else [],
                "header_rows": header_rows,
                "caption": payload.get("Caption", ""),
            }
        )
        el.text = payload.get("markdown") or "\n".join(" | ".join(r) for r in grid)
