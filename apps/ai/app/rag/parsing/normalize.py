"""⑥ Normalization — 파싱 전략 §6, §13.1⑥.

원칙: 모든 전처리는 "적용 조건 + 예외 조건 + 실패 시 무해(no-op)" 3종을 갖춘다.
조건 없는 전처리는 반드시 본문을 잘라먹는다.

실행 순서(§6.12)는 `pipeline.py`가 강제한다. 이 모듈은 각 단계를 함수로 제공한다.
"""
from __future__ import annotations

import re
import unicodedata

from app.rag.parsing.model import DocElement

INVISIBLE = dict.fromkeys(map(ord, "​‌‍﻿⁠"), None)
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

PAGE_NUM_PATTERNS = [
    re.compile(r"^-?\s*\d+\s*/\s*\d+\s*-?$"),      # 📏 "- 1 / 6 -"
    re.compile(r"^-?\s*\d+\s*-?$"),
    re.compile(r"^(page|페이지)\s*\d+", re.I),
]

# §6.2 예외 2 — 문서번호는 지우되 메타로 승격한다.
# 연도 4자리 세그먼트를 요구한다 — 팀명·저장소명(`SKN29-FINAL-1TEAM`)을 문서번호로
# 오인하면 잘못된 개정 추적 메타가 붙는다.
DOC_NO_RE = re.compile(r"\b[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)*-\d{4}(?:-[A-Z0-9]+)*\b")
EFFECTIVE_DATE_RE = re.compile(r"(\d{4})\s*[.\-년]\s*(\d{1,2})\s*[.\-월]\s*(\d{1,2})")
DOC_VERSION_RE = re.compile(r"(?:버전|version|Ver\.?|v)\s*[:\s]?\s*(\d+(?:\.\d+)*)", re.I)

BAND_RATIO = 0.08          # 📏 상·하단 8% 밴드
REPEAT_RATIO = 0.60        # 📏 페이지의 60% 이상 반복
SIZE_RATIO = 0.95          # 조건 3: 본문보다 작아야 함
REMOVAL_GUARD = 0.25       # §10.2 케이스 11 — 25% 초과 제거 시 no-op


def normalize_text(s: str, *, preserve_layout: bool = False) -> str:
    """§6.1 유니코드·공백 정규화 — [무조건 적용].

    📏 본 코퍼스 최우선 항목: 본문 문자의 17.0%가 NBSP(U+00A0)다.
    `preserve_layout=True`는 code_block/표 셀 전용(들여쓰기가 곧 정보).
    """
    if not s:
        return ""
    s = s.translate(INVISIBLE)
    s = unicodedata.normalize("NFKC", s)      # NBSP→SP, 전각→반각
    s = s.replace("\xa0", " ")                # NFKC가 놓치는 잔여분 방어
    s = _CTRL_RE.sub(" ", s)                  # 코퍼스 B의 \x01
    if preserve_layout:
        return s.rstrip()
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def signature(text: str) -> str:
    """숫자를 마스킹해 'p.1','p.2'를 같은 시그니처로 묶는다(§6.2)."""
    return re.sub(r"\d+", "#", normalize_text(text))


# ─────────────────────────── §6.2/§6.3 헤더·푸터 ───────────────────────────

def detect_boilerplate(
    elements: list[DocElement],
    *,
    n_pages: int,
    body_size: float,
    page_heights: dict[int, float],
) -> set[str]:
    """상·하단 밴드에서 '반복 + 위치 + 서식' 3조건 AND를 만족하는 라인만 확정."""
    band: dict[str, list[DocElement]] = {}
    for el in elements:
        height = page_heights.get(el.bbox.page, 0.0)
        if not height:
            continue
        # 📏 예외 1 — 표지(1페이지)는 헤더 판정 자체를 건너뛴다(제목이 상단에 있다).
        top = el.bbox.y0 < BAND_RATIO * height and el.bbox.page > 1
        bottom = el.bbox.y1 > (1 - BAND_RATIO) * height
        if top or bottom:
            band.setdefault(signature(el.text), []).append(el)

    threshold = max(3, int(n_pages * REPEAT_RATIO))
    sigs: set[str] = set()
    for sig, occ in band.items():
        pages = {e.bbox.page for e in occ}
        if len(pages) < threshold:                                   # 조건 1: 반복
            continue
        if min(e.attrs.get("size", body_size) for e in occ) >= body_size * SIZE_RATIO:
            continue                                                 # 조건 3: 서식
        sigs.add(sig)
    return sigs


def is_page_number(text: str) -> bool:
    t = normalize_text(text)
    return any(p.match(t) for p in PAGE_NUM_PATTERNS)


def strip_boilerplate(
    elements: list[DocElement],
    sigs: set[str],
) -> tuple[list[DocElement], list[DocElement], bool]:
    """확정된 시그니처와 페이지 번호를 제거한다.

    Fallback: 제거량이 전체 문자의 25%를 넘으면 **제거를 중단**한다(§10.2 케이스 11).
    본문을 지우느니 노이즈를 남기는 쪽이 안전하다.
    """
    total = sum(len(e.text) for e in elements) or 1
    kept: list[DocElement] = []
    removed: list[DocElement] = []
    for el in elements:
        drop = signature(el.text) in sigs or (
            is_page_number(el.text) and el.attrs.get("band") in ("top", "bottom")
        )
        # §6.3 예외: 하단 밴드라도 본문 폰트 크기면 제거하지 않는다.
        if drop and el.attrs.get("size_is_body"):
            drop = False
        (removed if drop else kept).append(el)

    if sum(len(e.text) for e in removed) / total > REMOVAL_GUARD:
        return elements, [], True      # no-op + 경고
    for el in removed:
        el.type = "page_number" if is_page_number(el.text) else (
            "header" if el.attrs.get("band") == "top" else "footer"
        )
    return kept, removed, False


def extract_doc_meta(removed: list[DocElement], elements: list[DocElement]) -> dict:
    """§6.2 예외 2 — 삭제 전에 문서번호·버전·시행일을 메타로 승격."""
    meta: dict[str, str] = {}
    for el in removed:
        m = DOC_NO_RE.search(el.text)
        if m and "doc_no" not in meta:
            meta["doc_no"] = m.group(0)
    for el in elements[:80]:                       # 표지·총칙 근처만 훑는다
        if "doc_no" not in meta:
            m = DOC_NO_RE.search(el.text)
            if m:
                meta["doc_no"] = m.group(0)
        if "doc_version" not in meta:
            m = DOC_VERSION_RE.search(el.text)
            if m:
                meta["doc_version"] = m.group(1)
    for el in elements:
        idx = el.text.find("시행")
        if idx >= 0:
            # "제정일 2026.7.20 / 시행일 2026.8.1"이 한 요소에 함께 오므로
            # 반드시 '시행' 이후 위치에서 날짜를 찾는다(제정일을 시행일로 오인 방지).
            m = EFFECTIVE_DATE_RE.search(el.text, idx)
            if m:
                meta["effective_date"] = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                break
    return meta


# ─────────────────────────── §6.8 문단 / §6.9 페이지 경계 ───────────────────────────

LIST_RE = re.compile(r"^\s*(?:\d+\.|[가-힣]\.|[①-⑳]|[-•·▪])\s")
# 📏 WeasyPrint가 리스트 마커를 본문과 다른 텍스트 런으로 렌더해 "1." 만 단독 라인이 된다.
# 그대로 두면 항 번호와 본문이 분리돼 인용 단위(호)가 깨진다.
MARKER_ONLY_RE = re.compile(r"^\s*(?:\d+\.|[가-힣]\.|[①-⑳]|[-•·▪])\s*$")
SECTION_START_RE = re.compile(r"^\s*(?:제\s*\d+\s*[장조절관]|별표\s*\d+|부칙|\d+\.\s|[가-힣]\.\s)")
SENT_FINAL_RE = re.compile(r"[.!?。」』\)]\s*$|[다요음함임][.]\s*$")


def _is_sentence_final(text: str) -> bool:
    return bool(SENT_FINAL_RE.search(text.strip()))


def merge_lines_to_paragraphs(elements: list[DocElement]) -> list[DocElement]:
    """§6.8 문단 경계 복원.

    신호: (a) 줄 간 수직 간격 > 행높이 × 1.5, (b) 좌측 x0 변화, (c) 직전 줄 문장 종결.
    예외: 리스트 항목(`1.` `가.` `-`)은 개별 `list_item`으로 유지한다 —
          규정의 "호(號)"가 뭉개지면 인용 단위가 깨진다.
    """
    out: list[DocElement] = []
    for el in elements:
        prev = out[-1] if out else None
        line_h = max(1.0, prev.bbox.y1 - prev.bbox.y0) if prev is not None else 1.0

        # ── 단독 마커 라인("1.")은 뒤따르는 본문을 끌어와 하나의 list_item으로 만든다.
        #    같은 줄에 좌측 배치되므로 x0 근접 조건은 적용하지 않는다.
        if (
            prev is not None
            and MARKER_ONLY_RE.match(prev.text)
            and el.type in ("paragraph", "list_item")
            and prev.bbox.page == el.bbox.page
            and el.bbox.y0 < prev.bbox.y1 + line_h * 0.8
            and el.attrs.get("size", 0) <= prev.attrs.get("size", 0) + 0.3   # 헤딩 보호
        ):
            prev.text = f"{prev.text} {el.text}".strip()
            prev.type = "list_item"
            prev.bbox.x1 = max(prev.bbox.x1, el.bbox.x1)
            prev.bbox.y1 = max(prev.bbox.y1, el.bbox.y1)
            continue

        if (
            prev is not None
            and el.type == "paragraph"
            and not MARKER_ONLY_RE.match(el.text)
            and prev.type in ("paragraph", "list_item")
            and prev.bbox.page == el.bbox.page
            and not LIST_RE.match(el.text)
            and not SECTION_START_RE.match(el.text)
            and not _is_sentence_final(prev.text)      # 종결된 항에는 다음 문단을 붙이지 않는다
            # 문단 이어지는 줄은 폰트 크기가 같다. 크기가 다르면 헤딩→본문 전환이므로
            # 병합하면 헤딩이 본문에 흡수돼 TOC 앵커 매칭이 깨진다.
            and abs(prev.attrs.get("size", 0.0) - el.attrs.get("size", 0.0)) < 0.3
        ):
            gap = el.bbox.y0 - prev.bbox.y1
            # 리스트 항목의 이어지는 줄은 마커가 아니라 본문에 맞춰 들여쓰기된다.
            aligned = abs(prev.bbox.x0 - el.bbox.x0) <= 12 or (
                prev.type == "list_item" and el.bbox.x0 >= prev.bbox.x0
            )
            if gap <= line_h * 1.5 and aligned:
                prev.text = f"{prev.text} {el.text}".strip()
                prev.bbox.x1 = max(prev.bbox.x1, el.bbox.x1)
                prev.bbox.y1 = max(prev.bbox.y1, el.bbox.y1)
                continue
        out.append(el)
    return out


def can_merge_across_pages(prev_el: DocElement, next_el: DocElement) -> bool:
    """§6.9 — 이전 페이지 마지막 본문과 다음 페이지 첫 본문의 병합 판정.

    📏 6페이지 중 4곳에서 문장이 페이지 중간에서 끊긴다(실측).
    반드시 헤더/푸터 **제거 후** 실행해야 발동한다.
    """
    if prev_el.type != next_el.type:
        return False
    if next_el.type in ("heading", "table", "code_block"):
        return False
    if SECTION_START_RE.match(next_el.text):
        return False
    if _is_sentence_final(prev_el.text):
        return False
    if abs(prev_el.bbox.x0 - next_el.bbox.x0) > 12:
        return False
    return True


def merge_across_pages(elements: list[DocElement]) -> list[DocElement]:
    out: list[DocElement] = []
    for el in elements:
        prev = out[-1] if out else None
        if prev is not None and el.bbox.page == prev.bbox.page + 1:
            if can_merge_across_pages(prev, el):
                prev.text = f"{prev.text} {el.text}".strip()
                prev.attrs["page_span"] = [prev.bbox.page, el.bbox.page]
                continue
            if not _is_sentence_final(prev.text) and prev.type in ("paragraph", "list_item"):
                # 📏 병합은 못 하지만 앞 문장이 미완결인 케이스(p3끝 "…지출" → p4 "2.").
                # 문자열 병합이 아니라 트리 소속으로 문맥을 보존한다(§6.9 예외).
                prev.attrs["truncated"] = True
        out.append(el)
    return out


# ─────────────────────────── §6.10 각주 ───────────────────────────

FOOTNOTE_RE = re.compile(r"^[\[\(]?\d+[\]\)]?\s+\S")


def classify_footnotes(elements: list[DocElement], page_heights: dict[int, float], body_size: float) -> None:
    """하단 밴드 + 본문보다 작은 폰트 + 마커 패턴 → `type="footnote"`."""
    for el in elements:
        if el.type != "paragraph":
            continue
        height = page_heights.get(el.bbox.page, 0.0)
        if not height:
            continue
        if (
            el.bbox.y1 > (1 - BAND_RATIO * 2) * height
            and el.attrs.get("size", body_size) < body_size * SIZE_RATIO
            and FOOTNOTE_RE.match(el.text)
        ):
            el.type = "footnote"
