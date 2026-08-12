"""C7. 문서 메타 승격 — `pdf_parsing_strategy.md` §5 C7. [REGULATION · LAW]

**보일러플레이트는 지우기 전에 메타로 승격한다.** 문서번호를 무조건 버리면 개정 추적이
불가능해진다.

- 규정: 표지 표에 `제정일 / 시행일 / 소관부서`, 머리말에 `TIGER-REG-2026-003`
- 법령: `[시행 2026. 1. 2.] [법률 제21065호, 2025. 10. 1., 타법개정]`
"""
from __future__ import annotations

import re

from app.rag.parsing.model import Element

_DOC_NO = re.compile(r"\b([A-Z]{2,}-[A-Z]{2,}-\d{4}-\d{3}(?:-\d+)?)\b")
_LAW_NO = re.compile(r"\[?(법률\s*제\d+호)")
_EFFECTIVE = re.compile(r"\[\s*시행\s*(\d{4}\.\s*\d{1,2}\.\s*\d{1,2})\.?\s*\]")
_REVISION_LINE = re.compile(r"개정이력\s*(.+)")
_DATE = re.compile(r"(\d{4}\.\s*\d{1,2}\.\s*\d{1,2})")

_COVER_KEYS = {
    "제정일": "enacted_date",
    "시행일": "effective_date",
    "소관부서": "owner_dept",
    "문서번호": "doc_no",
}


def _clean_date(raw: str) -> str:
    return re.sub(r"\s+", "", raw).rstrip(".")


def apply(elements: list[Element]) -> dict:
    """문서 메타를 추출해 dict로 돌려준다. 요소는 지우지 않는다(삭제는 별도 단계 책임)."""
    meta: dict[str, str] = {}

    for el in elements:
        text = el.text

        # ── 표지 표: 키-값 2열 구조
        for row in el.attrs.get("grid") or []:
            if len(row) < 2:
                continue
            key = re.sub(r"\s+", "", str(row[0]))
            if key in _COVER_KEYS and str(row[1]).strip():
                value = str(row[1]).strip()
                meta.setdefault(
                    _COVER_KEYS[key],
                    _clean_date(value) if "일" in key else value,
                )

        if (m := _DOC_NO.search(text)):
            meta.setdefault("doc_no", m.group(1))
        if (m := _LAW_NO.search(text)):
            meta.setdefault("doc_no", re.sub(r"\s+", "", m.group(1)))
        if (m := _EFFECTIVE.search(text)):
            meta.setdefault("effective_date", _clean_date(m.group(1)))
        if (m := _REVISION_LINE.search(text)):
            meta.setdefault("revision_history", m.group(1).strip()[:500])

    # 조문별 개정 배지(C6 산물) 중 최신 버전을 문서 개정 버전으로 올린다
    versions = [
        el.attrs["revision"] for el in elements if el.attrs.get("revision")
    ]
    if versions:
        meta.setdefault("revision", max(versions, key=_version_key))
    return meta


def _version_key(raw: str) -> tuple:
    nums = re.findall(r"\d+", raw)
    return tuple(int(n) for n in nums[:3])
