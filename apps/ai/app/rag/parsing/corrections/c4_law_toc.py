"""C4. 법령 목차 블록 제거 · HTML unescape — `pdf_parsing_strategy.md` §5 C4. [LAW]

법령 PDF는 앞머리에 **조문 제목 수백 개가 한 줄짜리 코드블록**으로 덤프된다. 그대로 두면
거대 노이즈 청크가 되어 **어떤 질의에나 어중간하게 걸린다**. 이것이 C4의 본체다.

⚠️ 조건 없는 코드블록 삭제는 금물이다 — 도해 문서의 ASCII 조직도가 같은 타입이고, 그쪽은
들여쓰기가 곧 조직 계층이다. 아래 3중 조건을 모두 만족할 때만 지운다.

📏 `unescape()`는 **우리 경로에서는 no-op이다.** `&lt;개정 …&gt;` 형태의 escape는 docling의
`export_to_markdown()` 산물이고, 우리는 `Element.text`를 직접 쓴다. 덤프 실측 —
`output/markdown/` 1,625건(법인세법 1,039 · 여신법 298 · 부가세법 288) vs
`output/layout|tables|parsed/` **0건**. 방어적으로 남겨 두었을 뿐이니, 마크다운 경로를
쓰게 되기 전까지 이 함수의 반환값을 성과 지표로 인용하지 말 것.
"""
from __future__ import annotations

import html
import re

from app.rag.parsing.model import Element

_TOC_ENTRY = re.compile(r"제\d+조(?:의\d+)?\s*[(（]")
_MIN_ENTRIES = 5            # 코드블록 안 조문 제목 수
_HEAD_RATIO = 0.2           # 문서 앞부분 20% 이내
_MAX_DROP_RATIO = 0.10      # 이보다 많이 지우게 되면 판정을 의심하고 중단한다


def _is_toc_block(el: Element) -> bool:
    return el.type == "code_block" and len(_TOC_ENTRY.findall(el.text)) >= _MIN_ENTRIES


def drop_toc_blocks(elements: list[Element], report) -> int:
    """목차 덤프 코드블록 제거. 삭제는 반드시 리포트에 남긴다."""
    limit = max(1, int(len(elements) * _HEAD_RATIO))
    targets = [el for el in elements[:limit] if _is_toc_block(el)]
    if not targets:
        return 0

    total_chars = sum(len(e.text) for e in elements) or 1
    if sum(len(e.text) for e in targets) / total_chars > _MAX_DROP_RATIO:
        report.warnings.append(
            f"C4: 목차 판정분이 본문의 {_MAX_DROP_RATIO:.0%}를 초과 — 제거 중단"
        )
        return 0

    for el in targets:
        el.attrs["dropped"] = "law_toc"
        report.dropped_elements.append(f"{el.element_id}: law_toc ({len(el.text)}자)")
    remaining = [el for el in elements if el.attrs.get("dropped") != "law_toc"]
    elements[:] = remaining
    return len(targets)


def unescape(elements: list[Element]) -> int:
    """`&lt;` `&gt;` `&amp;` 복원. 📏 **현 경로 실측 0건** — 모듈 docstring 참조."""
    changed = 0
    for el in elements:
        restored = html.unescape(el.text)
        if restored != el.text:
            el.text = restored
            el.mark("C4")
            changed += 1
        grid = el.attrs.get("grid")
        if grid:
            el.attrs["grid"] = [[html.unescape(str(c)) for c in row] for row in grid]
    return changed


def apply(elements: list[Element], report) -> int:
    dropped = drop_toc_blocks(elements, report)
    return dropped + unescape(elements)
