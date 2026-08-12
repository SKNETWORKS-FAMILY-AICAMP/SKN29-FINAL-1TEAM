"""결함 계측 — `pdf_parsing_strategy.md` §7.

교정 단계마다 **적용 전/후 양쪽을 재고 개선분을 리포트에 남긴다.** 도해 문서 회귀 사고가
바로 이 대조 없이는 보이지 않는다.

⚠️ 자간 계측은 토큰 단위로 한다. `([가-힣] ){3,}[가-힣]` 같은 **문자 단위** 정규식은
정상 한국어 문장("구현 시 두 기준을")도 잡아 실제보다 크게 부풀린다.
"""
from __future__ import annotations

import re

from app.rag.parsing.model import Element

_HANGUL = re.compile(r"[가-힣]")
_TRIM = re.compile(r"^[\s\"'“”‘’(){}\[\]「」『』·,.:;]+|[\s\"'“”‘’(){}\[\]「」『』·,.:;]+$")
# 홀로 설 수 없는 조사·어미 — 단독 토큰으로 나타나면 어절이 끊긴 것이다
_PARTICLES = frozenset("을 를 은 는 이 가 의 에 와 과 도 만 로 서 며 고 나 랑".split())
_ORPHAN_MARKER = re.compile(r"\s(\d{1,2})\.\s*$")
_CITATION_TAIL = re.compile(r"제\s*\d+\s*(조|항|호|장)\s*$")
_DATE_TAIL = re.compile(r"\d{1,4}\.\s*$")   # 앞도 "숫자."면 날짜 나열이지 마커가 아니다
_ESCAPE = re.compile(r"&(?:lt|gt|amp|quot|#\d+);")
_CIRCLED = re.compile(r"^\s*[①-⑮]")
_CHAPTER = re.compile(r"^제\s*(\d+)\s*장")
_ARTICLE = re.compile(r"^제\s*(\d+)\s*조")


def _tokens(text: str) -> list[str]:
    return [_TRIM.sub("", t) for t in text.split()]


def spacing_defects(elements: list[Element]) -> int:
    """자간 결함 요소 수 — ① 한 글자 토큰 3연속 이상 ② 조사만 홀로 떨어진 토큰."""
    count = 0
    for el in elements:
        if el.type == "code_block":
            continue
        toks = [t for t in _tokens(el.text) if t]
        run = 0
        hit = False
        for i, tok in enumerate(toks):
            run = run + 1 if len(tok) == 1 and _HANGUL.match(tok) else 0
            if run >= 3:
                hit = True
                break
            if i > 0 and tok in _PARTICLES:
                hit = True
                break
        count += hit
    return count


def orphan_markers(elements: list[Element]) -> int:
    """문단 끝에 남은 고아 항/호 마커 수 (C3 잔존분)."""
    count = 0
    for el in elements:
        if el.type not in ("paragraph", "list_item"):
            continue
        m = _ORPHAN_MARKER.search(el.text)
        if not m:
            continue
        head = el.text[: m.start()].rstrip()
        if _CITATION_TAIL.search(head) or _DATE_TAIL.search(head) or not _HANGUL.search(head):
            continue
        count += 1
    return count


def html_escapes(elements: list[Element]) -> int:
    return sum(len(_ESCAPE.findall(el.text)) for el in elements)


def auto_numbered_clauses(elements: list[Element]) -> int:
    """원문자 항인데 자동 번호가 붙을 경로에 남아 있는 요소 수 (C3 잔존분)."""
    return sum(
        1
        for el in elements
        if _CIRCLED.match(el.text)
        and el.type == "list_item"
        and not el.attrs.get("no_auto_number")
    )


def chapter_binding(elements: list[Element]) -> dict[str, object]:
    """장-조 귀속 정합성. 청킹이 실제로 기대는 값(§9 계약)을 그대로 검사한다."""
    chapters: list[int] = []
    articles: list[int] = []
    mis = 0
    for el in elements:
        if el.attrs.get("annex"):
            articles.clear()
            continue
        if (m := _CHAPTER.match(el.text)) and el.type in ("heading", "title"):
            chapters.append(int(m.group(1)))
        if (m := _ARTICLE.match(el.text)) and el.type in ("heading", "title"):
            articles.append(int(m.group(1)))
            if "chapter_no" not in el.attrs:
                mis += 1
    return {
        "chapters": chapters,
        "chapters_ordered": chapters == sorted(chapters),
        "articles_ordered": articles == sorted(articles),
        "articles_without_chapter": mis,
    }


def measure(elements: list[Element]) -> dict[str, object]:
    """한 문서의 결함 지표 묶음."""
    return {
        "elements": len(elements),
        "spacing_defects": spacing_defects(elements),
        "orphan_markers": orphan_markers(elements),
        "html_escapes": html_escapes(elements),
        "auto_numbered_clauses": auto_numbered_clauses(elements),
        **chapter_binding(elements),
    }
