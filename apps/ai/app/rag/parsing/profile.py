"""문서 유형 프로파일 판정 — `pdf_parsing_strategy.md` §4.1.

교정을 무조건 걸지 않는다. 실측된 결함은 전부 "문서 종류에 따라 존재하거나 존재하지 않는"
성질이라(법령엔 목차 덤프와 원문자 항이 있고, 도해 문서엔 계층 자체가 없다) 프로파일별로
단계를 켜고 끈다. 도해 문서에 계층 교정을 걸었다가 요소 일치율이 80%→53%로 회귀한 실측
사고가 이 게이트의 직접적 근거다.
"""
from __future__ import annotations

import re

from app.rag.parsing.model import Element, Profile

_ARTICLE = re.compile(r"^제\s*\d+\s*조\s*[(（]")
_LAW_TOC_ENTRY = re.compile(r"제\d+조(?:의\d+)?\s*[(（]")
_CIRCLED = re.compile(r"[①-⑮]")

# 판정 임계값 — 신호는 실측(docling_eval)에서 뽑았고, 경계값은 두 집단 사이가 넓어
# 둔감한 위치로 잡았다. 법령 3종만 코드블록 목차·원문자 항을 가지며, 도해 4종은
# 계층이 얕거나(Flat) 표 비중이 압도적이다(부서소개: 표 9 / 전체 요소 32).
_LAW_TOC_MIN_ENTRIES = 5        # 코드블록 하나에 조문 제목이 5개 이상이면 목차 덤프
_LAW_MIN_CIRCLED = 20           # 원문자 항 출현 수
_DIAGRAM_TABLE_RATIO = 0.15     # 표 요소 / 본문 요소
_REGULATION_MIN_ARTICLES = 3


def _is_law_toc_block(el: Element) -> bool:
    """코드블록 안에 조문 제목이 무더기로 들어간 목차 덤프인가."""
    return (
        el.type == "code_block"
        and len(_LAW_TOC_ENTRY.findall(el.text)) >= _LAW_TOC_MIN_ENTRIES
    )


def detect(elements: list[Element]) -> Profile:
    """요소 목록만 보고 문서 유형을 판정한다. 파일명·경로에 의존하지 않는다."""
    body = [e for e in elements if e.type not in ("header", "footer")]
    if not body:
        return "GENERIC"

    circled = sum(len(_CIRCLED.findall(e.text)) for e in body)
    if any(_is_law_toc_block(e) for e in body) or circled >= _LAW_MIN_CIRCLED:
        return "LAW"

    # 조(條) 구조가 있으면 규정형. 이 신호가 가장 강해서 먼저 본다.
    articles = sum(1 for e in body if _ARTICLE.match(e.text))
    if articles >= _REGULATION_MIN_ARTICLES:
        return "REGULATION"

    # 조문이 없고, 표가 내용의 실체이거나 계층이 얕으면 도해형.
    # ⚠️ 도해형이 막는 것은 "문서 종류"가 아니라 **연산의 성격**이다 — 요소 일치율을
    # 80%→53%로 되돌린 것은 문단 병합/분할 계열이었다. 재배열(C2)·요소 내 마커 이동(C3)은
    # 요소 경계를 넘지 않아 표를 흩뜨릴 수 없으므로 `PLANS["DIAGRAM"]`에서 켜 둔다
    # (직급체계에 실제 고아 마커 4건이 있다). 도해형에서 끄는 것은 C4·C7뿐이다.
    tables = sum(1 for e in body if e.type == "table")
    depth = max((e.level or 0) for e in body)
    if tables / len(body) >= _DIAGRAM_TABLE_RATIO or depth <= 1:
        return "DIAGRAM"
    return "GENERIC"
