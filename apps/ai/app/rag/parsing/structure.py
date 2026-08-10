"""⑦ Structure Reconstruction — 파싱 전략 §5.2, §13.1⑦.

3단 캐스케이드: 임베디드 TOC(1순위) → 폰트 크기(2순위) → 정규식(3순위).
세 층 모두 실패해도 문단 단위로 착지하되, 그때는 `structure_missing`을 **명시**한다.
구조를 못 찾는 것과 못 찾았다는 사실을 모르는 것은 전혀 다른 문제다.
"""
from __future__ import annotations

import hashlib
import re

from app.rag.parsing.model import DocElement, DocNode
from app.rag.parsing.normalize import normalize_text

HEADING_PATTERNS = [
    (1, re.compile(r"^제\s*(\d+)\s*장\b")),        # 제1장 총칙
    (1, re.compile(r"^별표\s*\d+\.")),             # 별표 1. 직책별 …
    (1, re.compile(r"^부칙\b")),
    (2, re.compile(r"^제\s*(\d+)\s*조\s*[\(（]")),  # 제9조 (사용 제한 …)
    (3, re.compile(r"^(\d+)\.\s")),                # 1. 항
    (4, re.compile(r"^([가-힣])\.\s")),            # 가. 호
]
ARTICLE_NO_RE = re.compile(r"제\s*(\d+)\s*조")

TOC_ANCHOR_THRESHOLD = 0.80
_MAX_HEADING_LEN = 120        # 이보다 긴 라인은 헤딩으로 보지 않는다


def _key(text: str) -> str:
    return "".join(normalize_text(text).split())


def _node_id(document_id: str, path: list[str]) -> str:
    digest = hashlib.sha1(" > ".join(path).encode("utf-8")).hexdigest()[:10]
    return f"{document_id}:{digest}"


# ─────────────────────────── 1순위: 임베디드 TOC ───────────────────────────

def match_toc_anchors(
    elements: list[DocElement],
    toc: list[tuple[int, str, int]],
) -> tuple[dict[int, tuple[int, str]], float]:
    """TOC 제목 문자열을 해당 페이지 본문 라인에서 조회한다.

    📏 코퍼스 A 실측: 116/116 = 100%. 구조 복원을 추론이 아니라 **조회**로 처리할 수
    있다는 뜻이며, 이것이 본 전략의 핵심 근거다.
    """
    by_page: dict[int, list[tuple[int, DocElement]]] = {}
    for idx, el in enumerate(elements):
        by_page.setdefault(el.bbox.page, []).append((idx, el))

    anchors: dict[int, tuple[int, str]] = {}
    used: set[int] = set()
    matched = 0
    for level, title, page_no in toc:
        target = _key(title)
        if not target:
            continue
        # TOC 페이지 번호가 어긋난 사례(§10.2 케이스 10) 대비로 ±1 페이지까지 본다.
        found = None
        for cand_page in (page_no, page_no + 1, page_no - 1):
            for idx, el in by_page.get(cand_page, []):
                if idx in used or el.type == "table":
                    continue
                key = _key(el.text)
                if key == target or (key.startswith(target) and len(key) <= len(target) + 40):
                    found = idx
                    break
            if found is not None:
                break
        if found is None:
            continue
        used.add(found)
        anchors[found] = (level, title)
        matched += 1
    rate = matched / len(toc) if toc else 0.0
    return anchors, rate


# ─────────────────────────── 2순위: 폰트 크기 ───────────────────────────

def font_size_headings(elements: list[DocElement], body_size: float) -> dict[int, tuple[int, str]]:
    """본문보다 큰 span 크기를 내림차순 배열해 레벨을 배정한다.

    📏 코퍼스 A: L1=12.3pt(52개), L2=10.6pt(64개) — 예외 0건.
    """
    sizes = sorted(
        {
            el.attrs.get("size", body_size)
            for el in elements
            if el.type in ("paragraph", "list_item")
            and el.attrs.get("size", body_size) > body_size + 0.3
            and len(el.text) <= _MAX_HEADING_LEN
        },
        reverse=True,
    )[:4]
    if not sizes:
        return {}
    level_of = {size: lvl for lvl, size in enumerate(sizes, start=1)}
    return {
        idx: (level_of[el.attrs.get("size", body_size)], el.text)
        for idx, el in enumerate(elements)
        if el.attrs.get("size", body_size) in level_of
        and el.type in ("paragraph", "list_item")
        and len(el.text) <= _MAX_HEADING_LEN
    }


# ─────────────────────────── 3순위: 정규식 ───────────────────────────

def regex_headings(elements: list[DocElement], *, max_level: int = 2) -> dict[int, tuple[int, str]]:
    """§5.2 3순위. 항(項)·호(號) 레벨은 TOC에도 폰트에도 없으므로 이 층이 반드시 필요하다.

    트리 구축에는 장·조(max_level=2)까지만 쓰고, 항 이하는 청킹 시 분할 경계로 쓴다.
    """
    out: dict[int, tuple[int, str]] = {}
    for idx, el in enumerate(elements):
        if el.type in ("table", "code_block", "header", "footer", "page_number"):
            continue
        if len(el.text) > _MAX_HEADING_LEN:
            continue
        for level, pattern in HEADING_PATTERNS:
            if level <= max_level and pattern.match(el.text):
                out[idx] = (level, el.text)
                break
    return out


# ─────────────────────────── 트리 조립 ───────────────────────────

def build_tree(
    elements: list[DocElement],
    *,
    document_id: str,
    document_title: str,
    toc: list[tuple[int, str, int]],
    body_size: float,
) -> tuple[DocNode, dict]:
    anchors, anchor_rate = match_toc_anchors(elements, toc) if toc else ({}, 0.0)
    source = "toc"

    if not (toc and anchor_rate >= TOC_ANCHOR_THRESHOLD):
        anchors = font_size_headings(elements, body_size)
        source = "fontsize"
        if not anchors:
            anchors = regex_headings(elements)
            source = "regex"

    # TOC/폰트로 잡은 뒤에도 정규식 헤딩을 보강한다 —
    # 📏 TOC에 없는 조문·별표가 남는 경우가 있다(레벨은 기존 신호와 충돌하지 않게 병합).
    if source in ("toc", "fontsize"):
        for idx, (level, title) in regex_headings(elements).items():
            anchors.setdefault(idx, (level, title))

    root = DocNode(
        node_id=_node_id(document_id, [document_title]),
        title=document_title,
        level=0,
        path=[document_title],
        page_start=elements[0].bbox.page if elements else 1,
        page_end=elements[-1].bbox.page if elements else 1,
    )
    stack: list[DocNode] = [root]
    heading_count = 0

    for idx, el in enumerate(elements):
        anchor = anchors.get(idx)
        if anchor and el.type not in ("table", "header", "footer", "page_number"):
            level, title = anchor
            el.type = "heading"
            el.level = level
            el.attrs["anchor_source"] = source
            heading_count += 1

            while len(stack) > 1 and stack[-1].level >= level:
                stack.pop()
            parent = stack[-1]
            path = [*parent.path, normalize_text(title)]
            node = DocNode(
                node_id=_node_id(document_id, path),
                title=normalize_text(title),
                level=level,
                path=path,
                parent=parent,
                page_start=el.bbox.page,
                page_end=el.bbox.page,
            )
            parent.children.append(node)
            stack.append(node)
            continue

        node = stack[-1]
        node.elements.append(el)
        node.page_end = max(node.page_end, el.bbox.page)
        for ancestor in stack:
            ancestor.page_end = max(ancestor.page_end, el.bbox.page)

    info = {
        "structure_source": source,
        "toc_entries": len(toc),
        "toc_anchor_rate": round(anchor_rate, 4),
        "headings": heading_count,
        "structure_missing": heading_count == 0,
    }
    return root, info


def article_no_of(title: str) -> int | None:
    m = ARTICLE_NO_RE.search(title)
    return int(m.group(1)) if m else None
