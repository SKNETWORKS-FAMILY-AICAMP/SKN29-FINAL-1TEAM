"""③ Parser Selection — 파싱 전략 §4.2, §4.3, §13.1③.

라우팅 단위는 문서가 아니라 **페이지**다. 규칙은 결정론적이어야 한다
(같은 입력 → 같은 파서 = 재현성).

새 PDF 유형 추가 = `PageParser` 구현 1개 + `register()` 1줄. 다운스트림 무변경.
"""
from __future__ import annotations

from app.rag.parsing.model import PageProfile
from app.rag.parsing.parsers.base import PageParser

PARSER_REGISTRY: dict[str, PageParser] = {}


def register(parser: PageParser) -> PageParser:
    PARSER_REGISTRY[parser.name] = parser
    return parser


def select_parsers(p: PageProfile) -> list[str]:
    """페이지 프로파일 → 파서 조합. 임계값 근거는 §4.2 실측.

    - `char_count < 50`: 📏 코퍼스 B 이미지 전용 슬라이드가 0~49자, 코퍼스 A 최소 146자
    - `ctrl_char_ratio > 0.02`: 📏 A=0.000 / B=0.111 — 간극이 5배 이상이라 둔감(안전)
    - `ruling_lines >= 4`: 표는 최소 외곽 4선
    """
    # ── 1. 텍스트 레이어 부재 → OCR (Type B)
    if p.char_count < 50 and p.image_area_ratio > 0.30:
        return ["ocr"]

    # ── 2. 글자 깨짐 → 텍스트 신뢰 불가 → OCR 재추출 (코퍼스 B 실측 케이스)
    if p.ctrl_char_ratio > 0.02:
        return ["ocr", "layout"]            # OCR 우선, layout은 대조군

    parsers = ["layout"]                    # ── 3. 기본

    if p.ruling_lines >= 4:                 # ── 4. 괘선 존재 → Table Parser 병행
        parsers.append("table")

    if p.col_clusters >= 2:                 # ── 5. 다단 → 컬럼 분리 모드
        parsers.append("multicolumn")

    return parsers
