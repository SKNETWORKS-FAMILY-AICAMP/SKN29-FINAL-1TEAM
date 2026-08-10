"""Layout Parser (기본) — 파싱 전략 §3.2, §13.1④.

PyMuPDF span dict의 `font/size/bbox`를 그대로 살려 라인 단위 DocElement를 만든다.
평문 추출이 잃는 것(헤딩 여부·읽기 순서·들여쓰기·위치)을 여기서 필드로 승격한다(§5.3).
"""
from __future__ import annotations

from collections import Counter
from typing import Any

import pymupdf

from app.rag.parsing.model import BBox, DocElement, PageProfile
from app.rag.parsing.normalize import BAND_RATIO, LIST_RE, normalize_text

_SIZE_EPS = 0.3


class LayoutParser:
    name = "layout"

    def can_handle(self, profile: PageProfile) -> float:
        if profile.char_count < 50:
            return 0.1
        return 0.9 if profile.ctrl_char_ratio <= 0.02 else 0.4

    def parse(self, page: pymupdf.Page, profile: PageProfile, ctx: dict[str, Any]) -> list[DocElement]:
        """`ctx["exclude_bboxes"]`(표 영역)와 겹치는 라인은 버린다.

        표 영역을 텍스트 흐름에서 제외하지 않으면 표 내용이 두 번 인덱싱된다(§13.1④).
        """
        document_id: str = ctx["document_id"]
        body_size: float = ctx.get("body_size", 10.0)
        exclude: list[tuple[float, float, float, float]] = ctx.get("exclude_bboxes", [])
        height = profile.height or float(page.rect.height)

        raw = page.get_text("dict")
        elements: list[DocElement] = []
        seq = 0

        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
                if not spans:
                    continue
                x0, y0, x1, y1 = line["bbox"]
                if _inside_any((x0, y0, x1, y1), exclude):
                    continue

                fonts = Counter(s.get("font", "") for s in spans)
                font = fonts.most_common(1)[0][0]
                size = round(max(float(s["size"]) for s in spans), 1)
                mono = "Mono" in font
                # 📏 Mono 폰트 = ASCII 조직도(코드블록) → 공백 정규화 예외(§6.1)
                raw_text = "".join(s["text"] for s in spans)
                text = normalize_text(raw_text, preserve_layout=mono)
                if not text.strip():
                    continue

                el_type = "code_block" if mono else (
                    "list_item" if LIST_RE.match(text) else "paragraph"
                )
                band = "top" if y0 < BAND_RATIO * height else (
                    "bottom" if y1 > (1 - BAND_RATIO) * height else "body"
                )

                seq += 1
                elements.append(
                    DocElement(
                        element_id=f"{document_id}:p{profile.page_no}:e{seq}",
                        type=el_type,
                        text=text,
                        bbox=BBox(profile.page_no, x0, y0, x1, y1),
                        parser=self.name,
                        confidence=0.9 if profile.ctrl_char_ratio <= 0.02 else 0.5,
                        attrs={
                            "size": size,
                            "font": font,
                            "band": band,
                            "size_is_body": abs(size - body_size) < _SIZE_EPS,
                            **({"no_split": True} if mono else {}),
                        },
                    )
                )

        # 읽기 순서: (y0, x0). 다단이면 컬럼 클러스터 우선(§13.1⑤).
        if profile.col_clusters >= 2:
            elements.sort(key=lambda e: (_col_key(e.bbox.x0, profile.width), e.bbox.y0, e.bbox.x0))
        else:
            elements.sort(key=lambda e: (round(e.bbox.y0, 1), e.bbox.x0))
        return _merge_code_blocks(elements)


def _col_key(x0: float, width: float) -> int:
    return int(x0 // max(1.0, width / 2))


def _inside_any(bbox: tuple[float, float, float, float], regions: list[tuple[float, float, float, float]]) -> bool:
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    return any(rx0 <= cx <= rx1 and ry0 <= cy <= ry1 for rx0, ry0, rx1, ry1 in regions)


def _merge_code_blocks(elements: list[DocElement]) -> list[DocElement]:
    """연속된 mono 라인을 한 code_block으로 묶는다(들여쓰기 = 조직 계층)."""
    out: list[DocElement] = []
    for el in elements:
        prev = out[-1] if out else None
        if prev is not None and prev.type == "code_block" and el.type == "code_block":
            prev.text = f"{prev.text}\n{el.text}"
            prev.bbox.x1 = max(prev.bbox.x1, el.bbox.x1)
            prev.bbox.y1 = max(prev.bbox.y1, el.bbox.y1)
            continue
        out.append(el)
    return out


parser = LayoutParser()
