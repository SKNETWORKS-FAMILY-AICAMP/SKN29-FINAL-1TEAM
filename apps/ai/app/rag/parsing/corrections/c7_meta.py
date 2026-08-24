"""C7. 문서 메타 승격 — `pdf_parsing_strategy.md` §5 C7. [REGULATION · LAW]

**보일러플레이트는 지우기 전에 메타로 승격한다.** 문서번호를 무조건 버리면 개정 추적이
불가능해진다.

- 규정: 표지 표에 `제정일 / 시행일 / 소관부서`, 머리말에 문서번호(예: `ORG-REG-2026-001`, 사용 시)
- 법령: `[시행 2026. 1. 2.] [법률 제21065호, 2025. 10. 1., 타법개정]`

**표지 표는 표로 안 잡히는 경우가 있다.** 📏 규정 4종 중 2종(업무추진비·회식)에서 docling이
같은 레이아웃의 표지를 `table`이 아니라 개별 `paragraph`로 흩뿌린다 — 키(`시행일`)와
값(`2026. 8. 1.`)이 인접 요소로 남는다. `grid`만 보면 시행일을 통째로 놓치므로 인접 요소
폴백을 함께 둔다(§`_cover_pairs`).
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


_COVER_VALUE_MAX = 120       # 인접 요소가 값이 아니라 본문 문단이면 걸러낸다


def _clean_date(raw: str) -> str:
    return re.sub(r"\s+", "", raw).rstrip(".")


def _put(meta: dict, key: str, value: str) -> None:
    """표지 키-값 한 쌍을 meta에 넣는다. 날짜 키는 형식을 정규화한다."""
    meta.setdefault(_COVER_KEYS[key], _clean_date(value) if "일" in key else value)


def _cover_pairs(meta: dict, elements: list[Element]) -> None:
    """표지 표가 표로 인식되지 않았을 때의 폴백 — 키 요소 **다음 요소**가 값이다.

    📏 업무추진비·회식 규정이 이 형태다(`시행일` / `2026. 8. 1.`이 각각 paragraph).
    본문 문장을 값으로 잘못 집는 것을 막으려고 두 가지를 건다 —
    ① 키 요소는 키 문자열 **뿐**이어야 한다(`시행일자는 …` 같은 문장 배제)
    ② 날짜 키는 값에 날짜꼴이 있어야 한다. 결측을 오값으로 바꾸는 것이 더 나쁘다.
    """
    for i, el in enumerate(elements[:-1]):
        key = re.sub(r"\s+", "", el.text)
        if key not in _COVER_KEYS:
            continue
        value = elements[i + 1].text.strip()
        if not value or len(value) > _COVER_VALUE_MAX:
            continue
        if "일" in key and not _DATE.search(value):
            continue
        _put(meta, key, value)


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
                _put(meta, key, str(row[1]).strip())

        if (m := _DOC_NO.search(text)):
            meta.setdefault("doc_no", m.group(1))
        if (m := _LAW_NO.search(text)):
            meta.setdefault("doc_no", re.sub(r"\s+", "", m.group(1)))
        if (m := _EFFECTIVE.search(text)):
            meta.setdefault("effective_date", _clean_date(m.group(1)))
        if (m := _REVISION_LINE.search(text)):
            meta.setdefault("revision_history", m.group(1).strip()[:500])

    # 표(grid)에서 못 얻은 것만 인접 요소 폴백으로 채운다 — 표가 있으면 표가 이긴다
    _cover_pairs(meta, elements)

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
