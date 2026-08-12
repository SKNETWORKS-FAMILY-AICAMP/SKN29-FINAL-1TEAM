"""C5. 페이지 경계 분할 표 병합 — `pdf_parsing_strategy.md` §5 C5.
[REGULATION · DIAGRAM · GENERIC]

인접 페이지에서 같은 열 구조의 표가 쪼개진다(실측 11건). 행 정확도 0.594의 주된 원인이고,
**열 정확도가 1.00인 것이 곧 "구조는 맞는데 행만 갈렸다"는 증거**다.

우선순위는 낮다 — 룰 임계값의 원천이 되는 핵심 한도표(직책별 한도·청탁금지법 별표)는
이미 무손실이고, 11건은 전부 부수 표다. **표는 어떤 경우에도 버리지 않는다.**
"""
from __future__ import annotations

import re

from app.rag.parsing.model import Element

_WS = re.compile(r"\s+")
_MAX_MERGED_ROWS = 40       # 넘으면 병합은 하되 청킹에서 분할하도록 표시


def _norm_row(row: list) -> tuple[str, ...]:
    return tuple(_WS.sub("", str(c)) for c in row)


def _only_furniture_between(elements: list[Element], a: int, b: int) -> bool:
    return all(
        elements[i].type in ("header", "footer", "caption")
        for i in range(a + 1, b)
    )


def apply(elements: list[Element]) -> int:
    """인접한 분할 표를 앞 표에 이어붙인다. 반환값은 병합 횟수."""
    indexed = [(i, el) for i, el in enumerate(elements) if el.type == "table"]
    merged_ids: set[int] = set()
    merges = 0

    for (i, prev), (j, cur) in zip(indexed, indexed[1:]):
        if id(prev) in merged_ids:
            continue
        pg, cg = prev.attrs.get("grid") or [], cur.attrs.get("grid") or []
        if not pg or not cg:
            continue
        if prev.attrs.get("cols") != cur.attrs.get("cols"):
            continue
        same_header = _norm_row(pg[0]) == _norm_row(cg[0])
        if not (same_header or _only_furniture_between(elements, i, j)):
            continue

        rows = cg[1:] if same_header else cg
        prev.attrs["grid"] = pg + rows
        prev.attrs["rows"] = len(prev.attrs["grid"])
        prev.attrs["page_span"] = [
            min(prev.attrs.get("page_span", [prev.page])[0], cur.page),
            max(prev.page, cur.page),
        ]
        prev.attrs["continued_from"] = prev.attrs.get("continued_from") or prev.element_id
        prev.text = "\n".join(" | ".join(str(c) for c in r) for r in prev.attrs["grid"])
        if prev.attrs["rows"] > _MAX_MERGED_ROWS:
            prev.attrs["split_on_chunk"] = True
        prev.mark("C5")

        cur.attrs["dropped"] = "merged_into_prev"
        cur.attrs["merged_into"] = prev.element_id
        merged_ids.add(id(cur))
        merges += 1

    if merges:
        elements[:] = [e for e in elements if e.attrs.get("dropped") != "merged_into_prev"]
    return merges
