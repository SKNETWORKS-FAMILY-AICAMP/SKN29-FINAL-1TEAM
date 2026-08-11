# -*- coding: utf-8 -*-
"""Docling 변환 결과 후처리 — 한국어 규정 PDF에서 관측된 파싱 결함 5종 교정.

`docling_parsing_test.ipynb` 진단 결과(`tiger_inc/pdf/*.pdf` 기준):

| 코드 | 증상 | 원인 |
|------|------|------|
| R1 | 페이지 최상단 중앙정렬 헤딩(`제N장 …`)이 그 페이지 맨 뒤로 밀림 | docling 리딩오더 후처리 |
| R2 | 목록 순번이 본문 끝으로 감 (`사적 용도의 지출 1.`) | 원본 PDF가 `<ol>` 마커를 콘텐츠 스트림 맨 뒤에 그림 |
| R3 | 한 문단이 두 요소로 쪼개짐 (`… 관리자 승` / `인을 받아 …`) | R2의 마커가 문단 중간에 끼어들어 bbox 그룹핑 실패 |
| R4 | 줄바꿈이 공백이 되어 어절이 깨짐 (`정산에 관 한 사항`) | CJK는 어절 중간에서 줄이 바뀌는데 docling은 공백으로 이어붙임 |
| R5 | 자간 제목의 글자마다 공백 (`타 이 거 주 식 회 사`) | 원본이 글자 사이에 실제 공백 문자를 넣음 |
| R6 | 두 항목이 한 덩어리로 뭉침 (`5. 여비교통비 … 6. 항목 구분이 …`) | R2의 마커가 문단 중간에 그려져 목록 경계를 못 잡음 |

R1~R3·R5·R6은 결정론적으로 복원된다. **R4만 원리상 완전 복원이 불가능하다** —
양끝맞춤(justify) 조판이라 어절 내 줄바꿈과 어절 경계 줄바꿈의 글리프 간격이
구분되지 않고(측정값 3.4pt vs 3.5pt), 줄 끝 공백 글리프도 PDF에 남지 않아
정보 자체가 소실돼 있다. 따라서 R4는 "줄 경계에 닿지 않아 훼손되지 않은 토큰"으로
만든 어휘 사전 + 구조·형태소 규칙 기반 추정이며, `score_line_joins()`로 정확도를
측정해 쓴다. tiger_inc 규정 4종 실측 — 요소 완전일치 29~54% → 77~96%.

전제 두 가지: R1은 **단(段)이 하나인 문서**, R4는 **이 문서군의 조판**에 맞춰져 있다.

사용:
    from postprocess import repair_document
    report = repair_document(doc, pdf_path)
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pypdfium2 as pdfium
from docling_core.types.doc import DocItemLabel, DoclingDocument, ListItem, TextItem

HANGUL = re.compile(r"[가-힣]")
WS = re.compile(r"\s+")
TRAILING_MARKER = re.compile(r"\s+(\d+)[.)]\s*$")
#: 어휘 사전 조회 시 떼어내는 문장부호
STRIP_CHARS = "\"'()（）「」『』[]{}·,.;:!?%…~-–—"
#: 줄 끝에 열려 있으면 다음 줄과 한 어절일 가능성이 매우 높은 여는 괄호
OPENERS = {"(": ")", "（": "）", "「": "」", "『": "』", "[": "]"}
#: 줄 끝이 이 부호면 병렬 나열이 이어지는 중이다 (`팀장·부서장·` + `본부장`)
CONNECTORS = "·/~-–—"
#: 줄 끝이 이 부호면 그 자리는 어절 경계다 (`확인하며,` + `이상 징후`).
#: 닫는 괄호는 제외한다 — 뒤에 조사가 바로 붙는다(`「법인카드 사용 규정」` + `과 동일한`).
CLOSERS = ",;:!?…"
#: 홑음절이지만 홀로 쓰이는 말 — 길이 휴리스틱이 이것들을 어절 조각으로 오인한다
STANDALONE_ONE = frozenset("및등각또즉단수것바때위내외전후")
#: 어절을 새로 시작할 수 없는 조사 — 정확히 일치할 때만 인정(접두 매칭은 오탐이 크다)
BOUND_EXACT = frozenset("의은는이가을를과와도만에서로")
#: 어절 첫머리에 올 수 없는 조사 (접두 매칭).
#: `한다`·`하며` 같은 하-계열은 보조용언으로 띄어 쓰이기도 해서(`등록하여야 한다`) 넣지 않는다.
BOUND_PREFIX = (
    "까지", "부터", "에서", "에게", "으로", "로서", "로써", "마다", "조차", "라고",
    "이며", "이고", "였다", "습니다", "입니다",
)


# --------------------------------------------------------------------------- #
# 원본 텍스트 레이어 인덱스
# --------------------------------------------------------------------------- #
@dataclass
class RawPage:
    """PDF 한 페이지의 원본 텍스트 + 공백 제거 색인.

    docling 텍스트는 줄바꿈이 공백으로 바뀌어 있어 원본과 문자열이 다르다.
    공백을 모두 지운 축약본(`squeezed`)으로 대조하면 그 차이를 무시하고
    원본 상의 위치를 찾을 수 있다.
    """

    page_no: int
    textpage: object
    raw: str = field(init=False)
    squeezed: str = field(init=False)
    _pos: list[int] = field(init=False)

    def __post_init__(self):
        self.raw = self.textpage.get_text_range()
        chars, pos = [], []
        for i, ch in enumerate(self.raw):
            if not ch.isspace():
                chars.append(ch)
                pos.append(i)
        self.squeezed = "".join(chars)
        self._pos = pos

    def locate_span(self, text: str) -> tuple[int, int] | None:
        """docling 텍스트에 대응하는 원본 문자 인덱스 구간 [start, end]."""
        key = WS.sub("", text)
        if not key:
            return None
        at = self.squeezed.find(key)
        if at < 0:
            return None
        return self._pos[at], self._pos[at + len(key) - 1]

    def locate(self, text: str) -> str | None:
        """docling 텍스트에 대응하는 원본 슬라이스(줄바꿈 보존)를 돌려준다."""
        span = self.locate_span(text)
        return None if span is None else self.raw[span[0] : span[1] + 1]

    def contains(self, text: str) -> bool:
        key = WS.sub("", text)
        return bool(key) and key in self.squeezed

    def glyph_gaps(self, start: int, end: int) -> list[tuple[int, float]]:
        """구간 내 인접 글리프 사이의 수평 간격 — (원본 인덱스, 간격).

        인덱스는 뒤 글리프의 위치다. 줄이 바뀌는 지점(x가 되돌아감)은 제외한다.
        """
        gaps, prev = [], None
        for i in range(start, end + 1):
            if self.raw[i].isspace():
                continue
            box = self.textpage.get_charbox(i)
            if prev is not None and box[0] >= prev:
                gaps.append((i, box[0] - prev))
            prev = box[2]
        return gaps


def read_raw_pages(pdf_path: Path) -> dict[int, RawPage]:
    """1-base 페이지 번호 -> RawPage."""
    doc = pdfium.PdfDocument(str(pdf_path))
    return {i + 1: RawPage(i + 1, doc[i].get_textpage()) for i in range(len(doc))}


# --------------------------------------------------------------------------- #
# R4: 줄바꿈 재결합용 어휘 사전
# --------------------------------------------------------------------------- #
def build_vocabulary(pdf_paths) -> Counter:
    """줄 경계에 닿지 않은 토큰만 모은다 — 줄 첫/마지막 토큰은 훼손 후보라 제외."""
    vocab: Counter = Counter()
    for path in pdf_paths:
        doc = pdfium.PdfDocument(str(path))
        for i in range(len(doc)):
            for line in doc[i].get_textpage().get_text_range().split("\r\n"):
                tokens = line.split()
                for token in tokens[1:-1]:
                    token = token.strip(STRIP_CHARS)
                    if token:
                        vocab[token] += 1
    return vocab


def _has_open_bracket(text: str) -> bool:
    """줄 끝 기준으로 닫히지 않은 여는 괄호가 있는가."""
    stack = []
    for ch in text:
        if ch in OPENERS:
            stack.append(OPENERS[ch])
        elif stack and ch == stack[-1]:
            stack.pop()
    return bool(stack)


#: 판정 규칙별 신뢰도 — `review.py`가 검수 시트에서 위험한 판정을 골라내는 데 쓴다.
#: strong = 구조적 단서나 사전 근거가 있음 / weak = 근거 없이 추측함
RULE_CONFIDENCE = {
    "closer": "strong",       # 앞줄이 문장부호로 끝남 → 어절 경계
    "bracket": "strong",      # 괄호가 안 닫힘 → 한 어절 계속
    "connector": "strong",    # `·` 등 연결부호로 끝남 → 나열 계속
    "bound-prefix": "strong", # 뒷조각이 어절을 시작할 수 없는 조사
    "vocab-joined": "strong", # 붙인 형태만 사전에 있음
    "vocab-split": "strong",  # 양쪽 낱말만 사전에 있음
    "vocab-freq": "strong",   # 양쪽 다 사전에 있어 빈도로 결정
    "bound-exact": "weak",    # 홑음절 조사 추정
    "standalone": "weak",     # 홑음절이지만 홀로 쓰이는 말 추정
    "length": "weak",         # 근거 없음 — 조각 길이로 찍음
}


def explain_join(tail: str, head: str, vocab: Counter) -> tuple[bool, str]:
    """`join_without_space`와 같은 판정을 하되 **어떤 규칙이 발동했는지**도 돌려준다.

    판정 순서가 곧 신뢰도 순서다 — 구조적 단서(괄호·연결부호) → 어휘 사전 →
    형태소 단서 → 길이 휴리스틱. 정답지가 없는 문서는 이 규칙 이름으로
    검수 우선순위를 정한다(`RULE_CONFIDENCE`).

    Returns: (공백 없이 붙일 것인가, 규칙 이름)
    """
    if tail.endswith(tuple(CLOSERS)) or (tail.endswith(".") and not tail[-2:-1].isdigit()):
        return False, "closer"
    if _has_open_bracket(tail):
        return True, "bracket"
    if tail.endswith(tuple(CONNECTORS)):
        return True, "connector"
    joined = (tail + head).strip(STRIP_CHARS)
    t, h = tail.strip(STRIP_CHARS), head.strip(STRIP_CHARS)
    if h.startswith(BOUND_PREFIX):
        return True, "bound-prefix"
    n_j, n_t, n_h = vocab.get(joined, 0), vocab.get(t, 0), vocab.get(h, 0)
    if n_j and not (n_t and n_h):
        return True, "vocab-joined"
    if n_t and n_h and not n_j:
        return False, "vocab-split"
    if n_j:
        return n_j >= min(n_t, n_h), "vocab-freq"
    # 사전에 없는 조합: 홑음절 조사는 어절을 시작할 수 없다.
    # (`이`·`도`처럼 관형사로도 쓰이는 글자가 있어 사전 판정보다 뒤에 둔다)
    if h in BOUND_EXACT:
        return True, "bound-exact"
    if h in STANDALONE_ONE:
        return False, "standalone"
    # 그래도 모르겠으면 1~2음절 조각은 어절 중간일 확률이 높다
    return (len(t) <= 2 or len(h) <= 2), "length"


def join_without_space(tail: str, head: str, vocab: Counter) -> bool:
    """줄 경계를 공백 없이 붙일지(=어절 중간에서 줄이 바뀌었는지) 판정."""
    return explain_join(tail, head, vocab)[0]


def rejoin_lines(raw_slice: str, vocab: Counter, trace: list | None = None) -> str:
    """원본 슬라이스의 줄바꿈을 한국어 규칙으로 되붙인다.

    `trace`를 주면 경계마다 `(tail, head, 붙였는가, 규칙이름)`을 append 한다
    (검수 시트용 — `review.py`).
    """
    lines = [ln.strip() for ln in raw_slice.split("\r\n") if ln.strip()]
    if not lines:
        return ""
    out = lines[0]
    for line in lines[1:]:
        tail, head = out.split()[-1], line.split()[0]
        # 어느 한쪽이라도 한글에 닿아 있어야 한국어 줄바꿈 판정 대상이다
        # (`별표 1` + `의 직책별` 처럼 앞이 숫자로 끝나는 경우도 포함)
        if HANGUL.match(tail[-1]) or HANGUL.match(head[0]):
            join, rule = explain_join(tail, head, vocab)
        else:
            join, rule = False, "non-hangul"
        if trace is not None:
            trace.append((tail, head, join, rule))
        out = f"{out}{'' if join else ' '}{line}"
    return out


# --------------------------------------------------------------------------- #
# 개별 교정
# --------------------------------------------------------------------------- #
def _page_of(item) -> int | None:
    prov = getattr(item, "prov", None) or []
    return prov[0].page_no if prov else None


def _top_of(item) -> float | None:
    prov = getattr(item, "prov", None) or []
    return prov[0].bbox.t if prov else None


def _span(node, doc) -> tuple[int, float]:
    """정렬 키 — 그룹 노드는 자손 중 첫 페이지·최상단 좌표를 대표값으로 쓴다."""
    pages, tops = [], []
    stack = [node]
    while stack:
        cur = stack.pop()
        page, top = _page_of(cur), _top_of(cur)
        if page is not None:
            pages.append(page)
            tops.append(top)
        stack.extend(ref.resolve(doc) for ref in getattr(cur, "children", []))
    if not pages:
        return (10**6, 0.0)
    first = min(pages)
    return (first, -max(t for p, t in zip(pages, tops) if p == first))


def repair_reading_order(doc: DoclingDocument) -> int:
    """R1 — 본문 최상위 요소를 페이지·상단좌표 순으로 안정 정렬.

    단(段)이 하나인 문서 전제. 다단 조판 PDF에는 적용하면 안 된다.
    """
    children = list(doc.body.children)
    keyed = [(_span(ref.resolve(doc), doc), i, ref) for i, ref in enumerate(children)]
    ordered = [ref for _, _, ref in sorted(keyed, key=lambda x: (x[0], x[1]))]
    moved = sum(1 for a, b in zip(children, ordered) if a.cref != b.cref)
    doc.body.children = ordered
    return moved


def repair_list_markers(doc: DoclingDocument) -> int:
    """R2 — 본문 끝으로 밀려난 순번을 떼어 `ListItem.marker` 로 되돌린다."""
    fixed = 0
    for item in doc.texts:
        if not isinstance(item, ListItem) or (item.marker or "").strip():
            continue
        m = TRAILING_MARKER.search(item.text)
        if not m:
            continue
        item.text = item.text[: m.start()].rstrip()
        item.orig = item.text
        item.marker = f"{m.group(1)}."
        item.enumerated = True
        fixed += 1
    return fixed


#: 두 요소가 "이어지는 줄"로 인정되는 세로 간격 상한(pt). 본문 행간 약 17pt.
LINE_GAP_LIMIT = 24.0


def _vertically_adjacent(prev, item) -> bool:
    """`item` 이 `prev` 바로 다음 줄인가 — 문단 사이 여백이면 False."""
    a = (getattr(prev, "prov", None) or [None])[0]
    b = (getattr(item, "prov", None) or [None])[0]
    if a is None or b is None:
        return False
    return -2.0 <= a.bbox.b - b.bbox.t <= LINE_GAP_LIMIT


def repair_split_items(doc: DoclingDocument, pages: dict[int, RawPage]) -> int:
    """R3 — 원본에서 이어지는 한 문단인데 두 요소로 쪼개진 건을 병합.

    판정 두 가지를 모두 만족해야 한다.
      ① 두 텍스트를 공백 없이 이으면 원본 페이지에 그대로 존재한다
         (`…경영지` + `원본부에 …` → 원본에 `경영지원본부에` 존재)
      ② 두 요소가 세로로 맞닿아 있다 — 공백 제거 대조만으로는 문단 사이
         빈 줄을 구분하지 못해, 떨어져 있는 두 문단까지 붙여버린다.
      ③ 앞 요소가 문장부호로 끝나지 않는다 — 쪼개진 문단의 앞 조각은 항상
         어절 중간에서 잘려 있다(`… 경영지`). 표지의 `제정일 2026. 7. 20.` 처럼
         온전히 끝난 줄은 다음 줄과 붙이면 안 된다.
    """
    merged, victims = 0, []
    children = [ref.resolve(doc) for ref in doc.body.children]
    # 리스트 그룹 내부까지 훑기 위해 평탄화
    flat: list = []
    for node in children:
        kids = [ref.resolve(doc) for ref in getattr(node, "children", [])]
        flat.extend(kids or [node])

    prev = None
    for item in flat:
        if not isinstance(item, TextItem) or item.label in (
            DocItemLabel.PAGE_HEADER,
            DocItemLabel.PAGE_FOOTER,
            DocItemLabel.SECTION_HEADER,
            DocItemLabel.TITLE,
        ):
            prev = None
            continue
        page = _page_of(item)
        if (
            prev is not None
            and _page_of(prev) == page
            and page in pages
            and not (item.marker.strip() if isinstance(item, ListItem) else "")
            and not prev.text.rstrip().endswith((".", "?", "!", ":", ";", ")"))
            and _vertically_adjacent(prev, item)
            and pages[page].contains(prev.text + item.text)
        ):
            prev.text = f"{prev.text}{item.text}"
            prev.orig = prev.text
            victims.append(item)
            merged += 1
            continue
        prev = item

    if victims:
        doc.delete_items(node_items=victims)
    return merged


def repair_line_joins(doc: DoclingDocument, pages: dict[int, RawPage], vocab: Counter) -> tuple[int, int]:
    """R4 — 원본 줄바꿈 위치를 되찾아 한국어 규칙으로 다시 이어붙인다.

    Returns: (교정된 요소 수, 원본에서 위치를 못 찾은 요소 수)
    """
    fixed = missed = 0
    for item in doc.texts:
        if item.label in (DocItemLabel.PAGE_HEADER, DocItemLabel.PAGE_FOOTER):
            continue
        page = _page_of(item)
        if page not in pages:
            continue
        raw_slice = pages[page].locate(item.text)
        if raw_slice is None:
            missed += 1
            continue
        rebuilt = rejoin_lines(raw_slice, vocab)
        if rebuilt and rebuilt != item.text:
            item.text = rebuilt
            item.orig = rebuilt
            fixed += 1
    return fixed, missed


def repair_embedded_markers(doc: DoclingDocument) -> int:
    """R6 — 한 항목 안에 다음 순번이 파묻힌 경우를 두 항목으로 쪼갠다.

    R2가 회수한 마커가 문단 중간에 그려져 있으면 docling이 두 항목을 한 덩어리로
    묶어버린다(`5. 여비교통비: … 아니다. 6. 항목 구분이 …`). 본문 중간에
    **바로 다음 번호**가 문장 끝 뒤에 나타날 때만 쪼갠다.
    """
    split = 0
    for item in list(doc.texts):
        if not isinstance(item, ListItem):
            continue
        m = re.match(r"(\d+)[.)]$", (item.marker or "").strip())
        if not m:
            continue
        nxt = int(m.group(1)) + 1
        hit = re.search(rf"(?<=[.)])\s+{nxt}[.)]\s+", item.text)
        if not hit:
            continue
        head, tail = item.text[: hit.start()].rstrip(), item.text[hit.end():].lstrip()
        if not tail:
            continue
        item.text, item.orig = head, head
        doc.insert_list_item(
            sibling=item,
            text=tail,
            enumerated=True,
            marker=f"{nxt}.",
            prov=(getattr(item, "prov", None) or [None])[0],
            after=True,
        )
        split += 1
    return split


def repair_letter_spacing(doc: DoclingDocument, pages: dict[int, RawPage]) -> int:
    """R5 — 자간이 벌어진 제목(`타 이 거 주 식 회 사`)의 글자 사이 공백을 제거.

    원본에 글자마다 공백이 들어 있어 문자열만으로는 어절 경계를 알 수 없다.
    글리프 간격을 재서 "중앙값의 1.8배 이상 벌어진 자리"만 진짜 띄어쓰기로 남긴다.
    """
    fixed = 0
    for item in doc.texts:
        if item.label in (DocItemLabel.PAGE_HEADER, DocItemLabel.PAGE_FOOTER):
            continue  # `- 2 / 7 -` 같은 쪽번호가 단음절 토큰 비율에 걸린다
        tokens = item.text.split()
        if len(tokens) < 4 or sum(len(t) == 1 for t in tokens) / len(tokens) < 0.6:
            continue
        page = _page_of(item)
        span = pages[page].locate_span(item.text) if page in pages else None
        if span is None:
            continue
        gaps = pages[page].glyph_gaps(*span)
        if len(gaps) < 3:
            continue
        widths = sorted(g for _, g in gaps)
        threshold = widths[len(widths) // 2] * 1.8
        keep = {i for i, g in gaps if g >= threshold}
        out = []
        for i in range(span[0], span[1] + 1):
            ch = pages[page].raw[i]
            if ch.isspace():
                continue
            if i in keep:
                out.append(" ")
            out.append(ch)
        rebuilt = "".join(out).strip()
        if rebuilt and rebuilt != item.text:
            item.text = rebuilt
            item.orig = rebuilt
            fixed += 1
    return fixed


# --------------------------------------------------------------------------- #
# 진입점
# --------------------------------------------------------------------------- #
#: 적용 순서 — 꼬리 마커를 먼저 떼어내야(R2) 원본 대조(R3·R4)가 성립한다.
#: `review.py`가 단계별 스냅샷을 뜰 때 이 순서를 그대로 따른다.
REPAIR_ORDER = ("R2", "R3", "R4", "R5", "R6", "R1")


def repair_document(doc: DoclingDocument, pdf_path, vocab_paths=None, steps=None) -> dict:
    """교정을 순서대로 적용하고 건수를 돌려준다 (doc을 제자리에서 수정).

    `steps`로 일부만 켤 수 있다 — 예: 법령 PDF는 R2 결함(목록 마커가 콘텐츠
    스트림 뒤로 밀림)이 없어서 그 2차 피해를 복구하는 R3가 오히려 조문을
    뭉쳐버린다. `steps={"R1", "R4", "R5"}` 처럼 지정해 끈다.
    """
    pdf_path = Path(pdf_path)
    on = set(REPAIR_ORDER) if steps is None else set(steps)
    pages = read_raw_pages(pdf_path)
    vocab = build_vocabulary(vocab_paths or [pdf_path])

    markers = repair_list_markers(doc) if "R2" in on else 0
    merges = repair_split_items(doc, pages) if "R3" in on else 0
    joins, missed = repair_line_joins(doc, pages, vocab) if "R4" in on else (0, 0)
    spacing = repair_letter_spacing(doc, pages) if "R5" in on else 0
    splits = repair_embedded_markers(doc) if "R6" in on else 0
    moved = repair_reading_order(doc) if "R1" in on else 0
    return {
        "steps": "+".join(s for s in REPAIR_ORDER if s in on),
        "R1_reordered": moved,
        "R2_markers_restored": markers,
        "R3_items_merged": merges,
        "R4_texts_rejoined": joins,
        "R4_unmatched": missed,
        "R5_letter_spacing": spacing,
        "R6_items_split": splits,
        "vocab_size": len(vocab),
    }


# --------------------------------------------------------------------------- #
# R4 채점 — md 원본을 정답지로 쓴다 (RAG 런타임 아님, 평가 전용)
# --------------------------------------------------------------------------- #
def normalize_markdown(text: str) -> str:
    """마크다운 장식을 걷어낸다 — 강조 기호는 **지우고**(`**굵게**란` → `굵게란`),
    구조 기호는 공백으로 바꾼다. 띄어쓰기 채점이 목적이라 공백은 보존해야 한다."""
    text = re.sub(r"[*`_]", "", text)
    return WS.sub(" ", re.sub(r"[#|>\[\]]", " ", text))


def score_line_joins(doc: DoclingDocument, pdf_path, reference_md, vocab_paths=None) -> dict:
    """교정된 doc의 텍스트가 md 원본과 얼마나 일치하는지 요소 단위로 채점."""
    ref = normalize_markdown(Path(reference_md).read_text(encoding="utf-8"))
    hit = miss = 0
    misses = []
    for item in doc.texts:
        if item.label in (DocItemLabel.PAGE_HEADER, DocItemLabel.PAGE_FOOTER):
            continue
        text = WS.sub(" ", item.text).strip()
        if len(text) < 10:
            continue
        if text in ref:
            hit += 1
        else:
            miss += 1
            misses.append(text)
    return {"exact": hit, "mismatch": miss, "samples": misses[:5]}
