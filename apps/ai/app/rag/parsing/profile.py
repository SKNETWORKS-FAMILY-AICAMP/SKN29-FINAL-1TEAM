"""② PDF Type Detection — 파싱 전략 §4.2, §13.1②.

문서 프로파일 + 페이지 프로파일을 산출해 파서 선택(③)의 근거를 만든다.
판정을 문서 단위로 굳히지 않는다 — 같은 문서 안에서 페이지 품질이 갈릴 수 있다.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path

import pymupdf

from app.rag.parsing.model import DocProfile, PageProfile

CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_COL_GAP = 60.0        # x0 클러스터 분리 간격(pt)
_RULING_THICKNESS = 2.5  # 이 값보다 얇은 도형은 괘선으로 본다


def _body_size(doc: pymupdf.Document) -> float:
    """문자수 가중 최빈 span 크기 = 본문 크기.

    📏 코퍼스 A: 본문 9.6/8.3pt, L1 12.3pt, L2 10.6pt, 헤더·푸터 7.0~7.7pt.
    """
    weights: Counter[float] = Counter()
    for page in doc:
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if text:
                        weights[round(float(span["size"]), 1)] += len(text)
    return weights.most_common(1)[0][0] if weights else 10.0


def _col_clusters(x0s: list[float]) -> int:
    """정렬된 x0의 간격이 `_COL_GAP` 이상이면 다른 컬럼으로 본다."""
    if len(x0s) < 4:
        return 1
    xs = sorted(x0s)
    clusters, current = [], [xs[0]]
    for x in xs[1:]:
        if x - current[-1] > _COL_GAP:
            clusters.append(current)
            current = [x]
        else:
            current.append(x)
    clusters.append(current)
    # 라인 3개 미만 클러스터는 표 셀·플로팅 요소의 잡음으로 보고 무시한다.
    return max(1, sum(1 for c in clusters if len(c) >= 3))


def profile_page(page: pymupdf.Page, page_no: int) -> PageProfile:
    rect = page.rect
    page_area = max(1.0, rect.width * rect.height)

    text = page.get_text("text")
    char_count = len(text.strip())
    ctrl_ratio = (len(CTRL_RE.findall(text)) / len(text)) if text else 0.0

    text_area, x0s = 0.0, []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            x0, y0, x1, y1 = line["bbox"]
            text_area += max(0.0, x1 - x0) * max(0.0, y1 - y0)
            x0s.append(round(x0, 1))

    image_area = 0.0
    try:
        for info in page.get_image_info():
            x0, y0, x1, y1 = info["bbox"]
            image_area += max(0.0, x1 - x0) * max(0.0, y1 - y0)
    except Exception:  # noqa: BLE001  # pragma: no cover - 드라이버 차이 방어
        image_area = 0.0

    ruling = 0
    try:
        for drawing in page.get_drawings():
            r = drawing["rect"]
            if r.width < _RULING_THICKNESS or r.height < _RULING_THICKNESS:
                ruling += 1
            elif drawing.get("type") in ("s", "fs"):   # 스트로크된 박스 = 표 외곽
                ruling += 4
    except Exception:  # noqa: BLE001  # pragma: no cover
        ruling = 0

    return PageProfile(
        page_no=page_no,
        width=rect.width,
        height=rect.height,
        char_count=char_count,
        area_ratio_text=min(1.0, text_area / page_area),
        image_area_ratio=min(1.0, image_area / page_area),
        ctrl_char_ratio=ctrl_ratio,
        ruling_lines=ruling,
        col_clusters=_col_clusters(x0s),
    )


def profile_document(
    doc: pymupdf.Document,
    *,
    document_id: str,
    source_path: str,
    document_name: str | None = None,
) -> DocProfile:
    toc = [(lvl, title, pno) for lvl, title, pno in (doc.get_toc() or [])]
    body = _body_size(doc)

    pages: list[PageProfile] = []
    seen_hashes: set[str] = set()
    toc_pages = {pno for _, _, pno in toc}

    for idx, page in enumerate(doc, start=1):
        prof = profile_page(page, idx)
        prof.has_toc_anchor = idx in toc_pages
        # §10.2 케이스 14 — 중복 페이지(텍스트 해시 동일)는 두 번째부터 스킵 대상.
        digest = hashlib.sha1(page.get_text("text").strip().encode("utf-8")).hexdigest()
        if prof.char_count >= 50:
            prof.is_duplicate = digest in seen_hashes
            seen_hashes.add(digest)
        pages.append(prof)

    return DocProfile(
        document_id=document_id,
        document_name=document_name or Path(source_path).stem,
        source_path=source_path,
        page_count=doc.page_count,
        producer=str(doc.metadata.get("producer") or ""),
        toc=toc,
        body_size=body,
        pages=pages,
        encrypted=bool(doc.needs_pass),
        repaired=bool(getattr(doc, "is_repaired", False)),
    )
