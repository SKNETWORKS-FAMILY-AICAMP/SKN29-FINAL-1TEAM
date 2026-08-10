"""OCR Parser — 파싱 전략 §3.1④, §14.1.

📏 현재 코퍼스(A·B)에 스캔 PDF(Type B)가 **존재하지 않는다.**
따라서 경로만 열어두고 기본 비활성이며, 파라미터는 실제 스캔본이 유입될 때 확정한다.
(없는 데이터로 파라미터를 지어내지 않는다)

유입 시 구현: PaddleOCR 한국어 > Tesseract kor. `requirements.txt`에 의존성 추가.
"""
from __future__ import annotations

from typing import Any

from app.rag.parsing.model import DocElement, PageProfile
from app.rag.parsing.parsers.base import ParserUnavailable


class OcrParser:
    name = "ocr"
    available = False

    def can_handle(self, profile: PageProfile) -> float:
        return 0.0 if not self.available else 0.8

    def parse(self, page: Any, profile: PageProfile, ctx: dict[str, Any]) -> list[DocElement]:
        raise ParserUnavailable(
            f"OCR 미설치 — p{profile.page_no}는 NEEDS_OCR 큐로 격리 (§10.2 케이스 4)"
        )


parser = OcrParser()
