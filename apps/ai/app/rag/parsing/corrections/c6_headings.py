"""C6. 헤딩 정제 — `pdf_parsing_strategy.md` §5 C6. [전 프로파일]

개정 배지가 헤딩 제목에 섞여 들어온다(실측 Text Mismatch 6건).

    "제2조 (정의) 개정 v1.1"  →  title="제2조 (정의)" + attrs["revision"]="v1.1"

제목과 개정 메타를 분리해야 `section_path` 인용 문자열이 깨끗해지고, 개정 추적도 조문
단위로 가능해진다. 분리에 실패하면 **원문 헤딩을 유지한다** — 인용이 조금 지저분한 것이
헤딩이 사라지는 것보다 낫다.
"""
from __future__ import annotations

import re

from app.rag.parsing.model import Element

# "개정 v1.1", "개정 v1.3(2026.7.28)", "제정 v1.0"
_REVISION = re.compile(r"\s*(?:개정|제정)\s*(v[\d.]+(?:\s*\([^)]*\))?)\s*$")


def apply(elements: list[Element]) -> int:
    changed = 0
    for el in elements:
        if el.type not in ("heading", "title"):
            continue
        m = _REVISION.search(el.text)
        if not m:
            continue
        title = el.text[: m.start()].rstrip()
        if not title:
            continue                        # 제목이 통째로 배지면 건드리지 않는다
        el.attrs["revision"] = re.sub(r"\s+", "", m.group(1))
        el.attrs["raw_title"] = el.text
        el.text = title
        el.mark("C6")
        changed += 1
    return changed
