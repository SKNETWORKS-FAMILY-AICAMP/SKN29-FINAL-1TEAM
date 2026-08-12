"""C2. 기하학적 리딩오더 복구 + 장-조 귀속 — `pdf_parsing_strategy.md` §5 C2.
[REGULATION · LAW · GENERIC]

**실측으로 규명된 원인**: docling이 일부 **페이지 최상단 요소를 그 페이지의 마지막 순서로
밀어낸다.** 규정 4종에서 장(章) 헤딩 8건이 정확히 여기 해당했다 —

    법인카드 p2: 제1조(top=666) → 제2조(572) → 제3조(277) → **제1장 총칙(top=717)**

그 결과 제1장 총칙이 제4조 앞에 놓여 **제4~7조가 총칙 소속으로 색인**된다. 부모-자식
정확도 0.737의 주범.

**따라서 헤딩 위치를 개별 교정하지 않는다.** 페이지 안에서 순서를 어긴 요소를 기하학적
위치로 되돌리면 장 귀속은 결과로 따라온다. 실측 위반은 11종 4,388요소 중 **21건**뿐이라
파급 범위가 작고, 단일 컬럼 문서면 어디에나 적용된다.
"""
from __future__ import annotations

import re

from app.rag.parsing.model import Element

CHAPTER = re.compile(r"^제\s*(\d+)\s*장")
ARTICLE = re.compile(r"^제\s*(\d+)\s*조")
# 조문 본문 시작형 — "제3조(납세의무자) ① …" 처럼 제목과 본문이 한 요소인 법령 조판
ARTICLE_BODY = re.compile(r"^제\s*\d+\s*조(?:의\d+)?\s*[(（]")
ANNEX = re.compile(r"^(별표|별지|부칙)")

_TOP_EPS = 1.0              # 같은 줄로 볼 수직 오차(pt)
_MAX_VIOLATION_RATIO = 0.25  # 이보다 많이 어긋나면 단일 컬럼 가정이 틀린 것으로 본다
_RATIO_MIN_ELEMENTS = 8     # 요소가 적은 페이지는 비율 판정을 적용하지 않는다
_MIN_BBOX_RATIO = 0.9       # bbox 결손이 많으면 기하 판정을 하지 않는다


def _violations(page_elements: list[Element]) -> list[Element]:
    """현재 순서 기준, 앞선 요소보다 물리적으로 위에 있는 요소들."""
    out, max_top = [], float("-inf")
    for el in page_elements:
        if max_top > float("-inf") and el.top > max_top + _TOP_EPS:
            out.append(el)
        max_top = max(max_top, el.top)
    return out


def reorder(elements: list[Element], report_warn) -> int:
    """페이지 단위로 읽기 순서를 기하학적 위치에 맞춰 되돌린다. 반환값은 이동한 요소 수."""
    body = [e for e in elements if e.type not in ("header", "footer")]
    furniture = [e for e in elements if e.type in ("header", "footer")]
    if not body:
        return 0

    with_bbox = sum(1 for e in body if e.bbox is not None)
    if with_bbox / len(body) < _MIN_BBOX_RATIO:
        report_warn("C2: bbox 결손이 많아 기하 판정을 건너뜀")
        return 0

    pages: dict[int, list[Element]] = {}
    for el in body:
        pages.setdefault(el.page, []).append(el)

    moved = 0
    for page, page_elements in pages.items():
        page_elements.sort(key=lambda e: e.order)
        bad = _violations(page_elements)
        if not bad:
            continue
        if (
            len(page_elements) >= _RATIO_MIN_ELEMENTS
            and len(bad) / len(page_elements) > _MAX_VIOLATION_RATIO
        ):
            # 다단 조판 등으로 단일 컬럼 가정이 깨진 페이지 — 건드리지 않는다.
            # (요소가 3~4개뿐인 표지 페이지는 위반 1건만으로 비율이 튀므로 제외한다)
            report_warn(f"C2: p{page} 순서 위반 {len(bad)}/{len(page_elements)} — 재배열 보류")
            continue
        page_elements.sort(key=lambda e: -e.top)    # 안정 정렬: 같은 높이는 원 순서 유지
        for el in bad:
            el.mark("C2")
        moved += len(bad)

    if moved:
        ordered: list[Element] = []
        for page in sorted(pages):
            ordered.extend(pages[page])
            ordered.extend(e for e in furniture if e.page == page)
        ordered.extend(e for e in furniture if e.page not in pages)
        elements[:] = ordered
        for i, el in enumerate(elements):
            el.order = i
    return moved


def bind_hierarchy(elements: list[Element], report_warn) -> int:
    """교정된 순서를 걸어가며 장-조 귀속을 요소에 새긴다.

    청킹은 장 헤딩의 **물리적 위치**가 아니라 여기서 새긴 `attrs["chapter_no"]`를 봐야 한다
    (전략 문서 §9 계약).
    """
    chapter_no = chapter_title = None
    article_no = None
    tagged = 0
    seen_chapters: list[int] = []
    seen_articles: list[int] = []

    for el in elements:
        if el.type in ("header", "footer"):
            continue
        text = el.text.strip()

        if ANNEX.match(text):
            # 별표·부칙은 장 소속이 아니라 최상위 형제다.
            # 부칙은 조 번호가 제1조부터 다시 시작하므로 단조성 추적도 여기서 끊는다.
            chapter_no = chapter_title = article_no = None
            seen_articles.clear()
            el.attrs["annex"] = True
            continue

        m = CHAPTER.match(text)
        if m and el.type in ("heading", "title"):
            chapter_no, chapter_title = int(m.group(1)), text
            article_no = None
            seen_chapters.append(chapter_no)
            el.attrs["chapter_no"] = chapter_no
            el.level = el.level or 1
            tagged += 1
            continue

        # 법령은 조가 heading이 아니라 paragraph로 잡히기도 한다 — 타입을 가리지 않는다.
        m = ARTICLE.match(text)
        if m and (el.type in ("heading", "title") or ARTICLE_BODY.match(text)):
            article_no = int(m.group(1))
            seen_articles.append(article_no)
            el.attrs["article_no"] = article_no
            if el.type in ("heading", "title"):
                el.level = el.level or 2

        if chapter_no is not None:
            el.attrs["chapter_no"] = chapter_no
            el.attrs["chapter_title"] = chapter_title
        if article_no is not None:
            el.attrs.setdefault("article_no", article_no)
        tagged += 1

    # 전제 검증 — 깨졌으면 되돌리지 않고 **알린다**. 조용한 실패가 더 나쁘다.
    if seen_chapters != sorted(seen_chapters):
        report_warn(f"C2: 장 번호가 여전히 뒤섞임 {seen_chapters} — 장 계층 신뢰 불가")
    if seen_articles != sorted(seen_articles):
        report_warn(f"C2: 조 번호 비단조 — 조 계층 신뢰 불가")
    return tagged


def apply(elements: list[Element], report_warn) -> int:
    moved = reorder(elements, report_warn)
    bind_hierarchy(elements, report_warn)
    return moved
