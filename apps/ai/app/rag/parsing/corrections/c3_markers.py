"""C3. 항(項)·호(號) 마커 복원 — `pdf_parsing_strategy.md` §5 C3. [REGULATION · LAW]

두 프로파일의 결함 형태가 다르다.

**REGULATION** — 목록 마커 박스가 항목 텍스트 뒤에 렌더돼 번호가 문단 꼬리에 붙는다(실측 95건).
    "사적 용도의 지출 1."   ← 이 "1."은 **자기 자신**의 번호다(1호). 다음 항의 것이 아니다.

**LAW** — `①②③`이 텍스트 맨 앞에 있는데 docling이 요소를 list_item으로 잡아,
마크다운 직렬화 때 오름차순 번호가 덧붙는다(실측 913건이 원문자로 시작).
    "3. ② 제1항에도 불구하고…"      ← "3."은 존재하지 않는 번호다

방치하면 **"제6조 제3항" 인용이 원천적으로 불가능**해진다.
"""
from __future__ import annotations

import re

from app.rag.parsing.model import Element

# 문단 끝 고아 마커 — "…법인카드를 발급한다. 1." 의 그 "1."
_ORPHAN = re.compile(r"\s(\d{1,2})\.\s*$")
# 오탐 방지 3종. 마커처럼 생겼지만 마커가 아닌 것들이다.
_CITATION_TAIL = re.compile(r"제\s*\d+\s*(조|항|호|장)\s*$")   # "…제10조." 의 마침표
# 바로 앞도 "숫자." 면 날짜·숫자 나열이지 마커가 아니다.
#   "2026. 7. 20."                      → 앞이 "7."
#   "<개정 2018. 12. 24., 2020. 12."    → 앞이 "2020."   ← 법령 개정일자 꼬리
_DATE_TAIL = re.compile(r"\d{1,4}\.\s*$")
_HANGUL = re.compile(r"[가-힣]")
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"
_LEADING_CIRCLED = re.compile(rf"^\s*([{_CIRCLED}])\s*")

_MERGEABLE = ("paragraph", "list_item")


def _clause_no(ch: str) -> int:
    return _CIRCLED.index(ch) + 1


def restore_orphan_markers(elements: list[Element]) -> int:
    """[REGULATION] 문단 끝 고아 마커를 그 문단의 **앞**으로 되돌린다.

    ⚠️ 마커는 **자기 자신의 번호**다. 다음 항의 번호가 아니다 — 실물 확인 결과 목록
    마커 박스가 항목 텍스트 뒤에 렌더돼 그렇게 보일 뿐이다.

        "사적 용도의 지출 1."            → 1호  "1. 사적 용도의 지출"
        "유흥업소, 사행성 업종에서의 지출 2."  → 2호

    한 칸 밀려 해석하면 모든 호 번호가 어긋나므로, 이 방향이 C3의 전부라 해도 좋다.
    """
    moved = 0
    for el in elements:
        if el.type not in _MERGEABLE:
            continue
        m = _ORPHAN.search(el.text)
        if not m:
            continue
        head = el.text[: m.start()].rstrip()
        # 날짜("2026. 7. 20.")·조문 인용("…제10조.")·순수 숫자 요소는 마커가 아니다
        if _CITATION_TAIL.search(head) or _DATE_TAIL.search(head) or not _HANGUL.search(head):
            continue

        number = int(m.group(1))
        el.attrs["clause_no"] = number
        el.attrs.setdefault("level_hint", 3)
        el.text = head if head.lstrip().startswith(f"{number}.") else f"{number}. {head}"
        el.mark("C3")
        moved += 1
    return moved


def preserve_circled_clauses(elements: list[Element]) -> int:
    """[LAW] 원문자로 시작하는 요소는 목록이 아니라 **항**이다. 자동 번호를 막는다."""
    fixed = 0
    for el in elements:
        m = _LEADING_CIRCLED.match(el.text)
        if not m:
            continue
        el.attrs["clause_no"] = _clause_no(m.group(1))
        el.attrs["no_auto_number"] = True       # 직렬화 시 ordered-list 번호를 붙이지 않는다
        el.attrs.setdefault("level_hint", 3)
        if el.type == "list_item":
            el.type = "paragraph"               # 오름차순 번호가 덧붙는 경로를 끊는다
        el.mark("C3")
        fixed += 1
    return fixed


_ARTICLE_START = re.compile(r"^\s*제\s*\d+\s*조(?:의\d+)?\s*[(（]")


def validate_sequences(elements: list[Element], report_warn) -> int:
    """조(條) 블록 안에서 항 번호가 연속인지 본다. 어긋나면 인용 신뢰도를 낮춘다.

    ⚠️ **1부터 시작할 것을 요구하지 않는다.** 법령은 제1항의 ①이 조 제목과 같은 줄에
    들어가는 일이 많아(`제3조(납세의무자) ① 다음 각 호의…`) 독립 요소로는 ②부터
    시작하는 것이 정상이다. 보는 것은 시작값이 아니라 **연속성**이다.
    """
    blocks: list[list[Element]] = [[]]
    for el in elements:
        # 법령은 조가 heading이 아니라 paragraph로 잡히기도 한다 — 텍스트로 경계를 본다.
        if _ARTICLE_START.match(el.text) or (
            el.type == "heading" and "article_no" in el.attrs
        ):
            blocks.append([])
        blocks[-1].append(el)

    broken = 0
    for block in blocks:
        numbers = [e.attrs["clause_no"] for e in block if "clause_no" in e.attrs]
        if len(numbers) < 2:
            continue
        if numbers == list(range(numbers[0], numbers[0] + len(numbers))):
            continue
        for e in block:
            if "clause_no" in e.attrs:
                e.attrs["marker_uncertain"] = True
        broken += 1
    if broken:
        report_warn(f"C3: 항 번호가 불연속인 조 {broken}개 — marker_uncertain 표시")
    return broken


def apply(elements: list[Element], profile: str, report_warn) -> int:
    count = 0
    if profile == "LAW":
        count += preserve_circled_clauses(elements)
    # 고아 마커 복원은 **요소 안에서만** 일어난다 — 병합·분할·재배열이 없으므로 표를
    # 흩뜨릴 수 없다. 도해형에 계층 교정을 금지한 회귀 사고는 문단 병합/분할 계열의
    # 문제였고, 도해 문서에도 실제 고아 마커가 있다(직급체계 4건). 그래서 여기는 연다.
    count += restore_orphan_markers(elements)
    validate_sequences(elements, report_warn)
    return count
