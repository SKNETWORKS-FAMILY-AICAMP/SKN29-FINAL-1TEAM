"""Table Parser — 파싱 전략 §7.1, §13.1④.

📏 본 시스템에서 표는 부수 요소가 아니라 핵심 데이터다.
['직책','1일 한도','월 한도'] 같은 값이 RuleGraph 조건의 임계값과 대응한다.
표가 뭉개지면 RAG 내규 검증이 무의미해진다.
"""
from __future__ import annotations

from typing import Any

from app.rag.parsing.model import BBox, DocElement, PageProfile
from app.rag.parsing.normalize import normalize_text

TABLE_SETTINGS = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
TEXT_SETTINGS = {"vertical_strategy": "text", "horizontal_strategy": "text"}
MIN_AREA_RATIO = 0.02      # §7.1.5 — 페이지의 2% 미만은 장식용 박스
MAX_ROWS_PER_CHUNK = 40    # §7.1.4 / §8.5


class TableParser:
    name = "table"

    def can_handle(self, profile: PageProfile) -> float:
        return 0.9 if profile.ruling_lines >= 4 else 0.1

    def parse(self, page: Any, profile: PageProfile, ctx: dict[str, Any]) -> list[DocElement]:
        """`page`는 pdfplumber Page. lines 전략 → 실패 시 text 전략(confidence 0.5)."""
        document_id: str = ctx["document_id"]
        page_area = max(1.0, profile.width * profile.height)

        found = _find(page, TABLE_SETTINGS)
        confidence = 1.0
        if not found and profile.ruling_lines >= 4:
            # §10.2 케이스 8 — 괘선이 이미지이거나 불연속인 경우의 폴백.
            found = _find(page, TEXT_SETTINGS)
            confidence = 0.5

        elements: list[DocElement] = []
        for seq, (table, grid) in enumerate(found, start=1):
            rows = len(grid)
            cols = max((len(r) for r in grid), default=0)
            # ── 실측 검증된 오탐 필터: 정탐 46/46, 오탐 35/35 제거, 오분류 0건
            #    (WeasyPrint가 `###` 헤딩을 좌측 보더 박스로 렌더한 1행×2열)
            if rows < 2 or cols < 2:
                continue
            x0, top, x1, bottom = table.bbox
            if ((x1 - x0) * (bottom - top)) / page_area < MIN_AREA_RATIO:
                continue

            elements.append(
                DocElement(
                    element_id=f"{document_id}:p{profile.page_no}:t{seq}",
                    type="table",
                    text=to_markdown(grid),                 # 임베딩 대상(§7.1.2)
                    bbox=BBox(profile.page_no, x0, top, x1, bottom),
                    parser=self.name,
                    confidence=confidence,
                    attrs={
                        "rows": rows,
                        "cols": cols,
                        "grid": grid,                       # 정확한 값 조회용 원본 셀 배열
                        "header_row": grid[0],
                    },
                )
            )
        return elements


def _find(page: Any, settings: dict) -> list[tuple[Any, list[list[str]]]]:
    out: list[tuple[Any, list[list[str]]]] = []
    try:
        tables = page.find_tables(settings)
    except Exception:  # noqa: BLE001  # pragma: no cover - 페이지 단위 실패 격리
        return out
    for table in tables:
        try:
            grid = [[_cell(c) for c in row] for row in table.extract()]
        except Exception:  # noqa: BLE001  # pragma: no cover
            continue
        if grid:
            out.append((table, grid))
    return out


def _cell(value: str | None) -> str:
    # 표 셀은 preserve_layout — 셀 안에서 줄바꿈만 공백으로 접는다(§6.7 예외 3).
    return " ".join(normalize_text(value or "", preserve_layout=True).split())


def to_markdown(grid: list[list[str]]) -> str:
    """§7.1.2 — 임베딩·LLM 컨텍스트에는 Markdown, 정확 조회에는 attrs["grid"]."""
    if not grid:
        return ""
    cols = max(len(r) for r in grid)
    rows = [list(r) + [""] * (cols - len(r)) for r in grid]
    header = rows[0]
    lines = [
        "| " + " | ".join(c.replace("|", "\\|") for c in header) + " |",
        "| " + " | ".join(["---"] * cols) + " |",
    ]
    for row in rows[1:]:
        lines.append("| " + " | ".join(c.replace("|", "\\|") for c in row) + " |")
    return "\n".join(lines)


def _norm_row(row: list[str]) -> tuple[str, ...]:
    return tuple(" ".join(c.split()) for c in row)


def merge_split_tables(elements: list[DocElement]) -> list[DocElement]:
    """§7.1.4 페이지·블록 분할 표 병합.

    📏 `부서소개` p2에서 동일 헤더 표 3개가 연속 검출된 실측 사례.
    병합해도 `attrs["page_span"]`으로 원 위치를 남겨 Citation을 보존한다.
    """
    out: list[DocElement] = []
    for el in elements:
        if el.type != "table":
            out.append(el)
            continue
        prev_idx = next((i for i in range(len(out) - 1, -1, -1) if out[i].type == "table"), None)
        prev = out[prev_idx] if prev_idx is not None else None
        between = out[prev_idx + 1:] if prev_idx is not None else []
        only_boilerplate = all(e.type in ("header", "footer", "page_number") for e in between)
        if (
            prev is not None
            and only_boilerplate
            and prev.attrs["cols"] == el.attrs["cols"]
            and _norm_row(prev.attrs["header_row"]) == _norm_row(el.attrs["header_row"])
        ):
            prev.attrs["grid"].extend(el.attrs["grid"][1:])       # 헤더 행 스킵
            prev.attrs["rows"] = len(prev.attrs["grid"])
            prev.text = to_markdown(prev.attrs["grid"])
            span = prev.attrs.get("page_span", [prev.bbox.page, prev.bbox.page])
            prev.attrs["page_span"] = [span[0], el.bbox.page]
            prev.attrs.setdefault("continued_from", []).append(el.element_id)
            prev.bbox.y1 = max(prev.bbox.y1, el.bbox.y1) if prev.bbox.page == el.bbox.page else prev.bbox.y1
            continue
        out.append(el)
    return out


parser = TableParser()
