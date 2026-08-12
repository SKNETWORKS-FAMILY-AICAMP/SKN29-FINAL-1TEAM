"""청크 직렬화 — 계층 헤더·인용 문자열·표 마크다운 (`chunking-strategy.md` §7).

여기서 만드는 문자열 3종이 청크의 "문맥 보존" 전부다.
  ① `header`   — 검색된 청크 하나만 봐도 어느 문서 어느 조문인지 알 수 있게 하는 앞머리
  ② `citation` — 회계 담당자에게 제시할 인용 문자열 (FR-RV). 메타가 아니라 **본문에도** 박는다
  ③ 표 마크다운 — `grid`에서 직접 만든다. docling 원본 md보다 우리 grid가 정확하다(셀 .965)
"""
from __future__ import annotations

import re

from app.rag.parsing.model import Element

ARTICLE_LABEL = re.compile(r"^제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")
CHAPTER_LABEL = re.compile(r"^제\s*(\d+)\s*장")
ANNEX_LABEL = re.compile(r"^\[?\s*(별표|부칙)")
_WS = re.compile(r"[ \t]+")


def article_label(text: str, article_no: int | None) -> str | None:
    """'제55조의2(토지등…)' → '제55조의2'. 원문 표기를 그대로 살린다.

    `attrs["article_no"]`는 정수라 `의2`를 잃는다. 인용 문자열이 '제55조'가 되면
    실제 제55조와 구별되지 않으므로, 표기는 헤딩 텍스트에서 다시 뽑는다.
    """
    m = ARTICLE_LABEL.match(text.strip())
    if m:
        return f"제{m.group(1)}조의{m.group(2)}" if m.group(2) else f"제{m.group(1)}조"
    return f"제{article_no}조" if article_no is not None else None


def article_title(text: str) -> str:
    """헤딩 텍스트에서 조 제목만 남긴다. 법령은 조 제목 뒤에 ①항 본문이 붙어 있다."""
    text = _WS.sub(" ", text.strip())
    m = re.match(r"^(제\s*\d+\s*조(?:\s*의\s*\d+)?\s*[（(][^)）]*[)）])", text)
    if m:
        return m.group(1).strip()
    # 괄호 제목이 없으면 첫 원문자 항 앞까지만
    return re.split(r"\s*[①-⑮]", text, maxsplit=1)[0].strip()[:80]


def citation(doc_name: str, label: str | None, kind: str | None,
             start: int | None, end: int | None) -> str:
    """'법인카드_사용규정 제9조 제1~3호'. 범위가 1건이면 '제1호'로 접는다."""
    parts = [doc_name]
    if label:
        parts.append(label)
    if kind and start is not None:
        span = f"제{start}{kind}" if end in (None, start) else f"제{start}~{end}{kind}"
        parts.append(span)
    return " ".join(parts)


def header(doc_name: str, meta: dict, chapter_title: str | None,
           article_head: str | None, cite: str) -> str:
    """계층 헤더. 3줄을 넘기지 않는다 — 본문 중앙값이 449자라 헤더가 길면 신호가 묽어진다.

        [법인카드_사용규정 v1.1 · 시행 2026-01-01]
        제2장 법인카드의 발급 및 관리 > 제9조 (사용 제한 및 금지 항목)
        ▸ 법인카드_사용규정 제9조 제1~3호
    """
    stamp = [doc_name]
    if meta.get("revision"):
        stamp.append(str(meta["revision"]))
    if meta.get("effective_date"):
        stamp.append(f"시행 {meta['effective_date']}")
    if meta.get("doc_no"):
        stamp.append(str(meta["doc_no"]))

    path = " > ".join(p for p in (chapter_title, article_head) if p)
    lines = [f"[{' · '.join(stamp)}]"]
    if path:
        lines.append(path)
    if cite and cite != path:
        lines.append(f"▸ {cite}")
    return "\n".join(lines)


def table_markdown(el: Element, row_slice: tuple[int, int] | None = None) -> str:
    """`attrs["grid"]`에서 마크다운 표를 만든다. 행 분할 시 헤더행을 반복한다(§6.4).

    grid가 없으면(엔진 실패) 원문 텍스트를 그대로 쓴다 — **표는 어떤 경우에도 버리지 않는다.**
    """
    grid = el.attrs.get("grid") or []
    if not grid or not isinstance(grid[0], list):
        return el.text

    header_rows = int(el.attrs.get("header_rows") or 1)
    head, body = grid[:header_rows], grid[header_rows:]
    if row_slice:
        body = body[row_slice[0]: row_slice[1]]

    width = max(len(r) for r in grid)
    def line(row: list) -> str:
        cells = [str(c).replace("|", "\\|").strip() for c in row] + [""] * (width - len(row))
        return "| " + " | ".join(cells) + " |"

    out = [line(r) for r in head]
    out.append("|" + "---|" * width)
    out += [line(r) for r in body]
    return "\n".join(out)


def lead_in(elements: list[Element], limit: int) -> str:
    """표 바로 앞의 도입 문장. 표 청크는 이것 없이는 무엇의 표인지 알 수 없다."""
    for el in reversed(elements):
        if el.type in ("caption", "paragraph", "list_item") and el.text.strip():
            text = el.text.strip()
            return text if len(text) <= limit else text[:limit] + "…"
    return ""
