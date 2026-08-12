"""파싱 중간 표현(CDM) — `llm_wiki/_context/pdf_parsing_strategy.md` §6.

docling의 `DoclingDocument`를 하류로 그대로 흘리지 않는다. 교정·청킹·메타가 docling
버전에 묶이면 엔진 업그레이드가 전부를 흔들기 때문에, 얇은 자체 표현 하나를 사이에 둔다.
엔진 이질성은 `engine.py`가 이 표현으로 변환하는 지점에서 끊긴다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ElementType = Literal[
    "title", "heading", "paragraph", "list_item", "table",
    "figure", "caption", "footnote", "code_block", "header", "footer",
]

# 문서 유형 프로파일 (§4) — 교정 단계를 켜고 끄는 기준
Profile = Literal["REGULATION", "LAW", "DIAGRAM", "GENERIC"]


@dataclass
class Element:
    """문서 요소 하나. 교정 계층은 이 리스트를 입력받아 이 리스트를 돌려준다."""

    element_id: str                 # "{doc_id}:p{page}:e{seq}"
    type: ElementType
    text: str                       # 교정 후 텍스트 (표는 Markdown 직렬화)
    page: int
    order: int                      # 문서 전체 읽기 순서 (전역 단조 증가)
    level: int | None = None        # heading 전용: 1=장 2=조 3=항 4=호
    bbox: tuple[float, float, float, float] | None = None   # (l, t, r, b) PDF 좌표
    attrs: dict[str, Any] = field(default_factory=dict)
    # attrs 관례:
    #   table    → rows / cols / grid / header_row / page_span / continued_from
    #   heading  → revision / article_no / chapter_no
    #   교정     → corrections(list[str]) / marker_uncertain(bool) / dropped(str)

    @property
    def top(self) -> float:
        """bbox 상단 y. 기하학적 리딩오더(C2) 판정에 쓴다. bbox 없으면 -inf."""
        return self.bbox[1] if self.bbox else float("-inf")

    def mark(self, step: str) -> None:
        """이 요소에 적용된 교정 단계를 기록한다 — 검색 결과 이상 시 추적용."""
        self.attrs.setdefault("corrections", []).append(step)


@dataclass
class ParseReport:
    """무엇을 했고 무엇을 건너뛰었는지. 조용한 실패가 RAG 품질 저하의 최대 원인이다."""

    profile: Profile = "GENERIC"
    applied_steps: list[str] = field(default_factory=list)
    skipped_steps: dict[str, str] = field(default_factory=dict)     # {"C2": "SKIP:no_bbox"}
    corrections_count: dict[str, int] = field(default_factory=dict)
    dropped_elements: list[str] = field(default_factory=list)       # 삭제는 반드시 기록
    warnings: list[str] = field(default_factory=list)
    scores: dict[str, float] | None = None

    def applied(self, step: str, count: int) -> None:
        self.applied_steps.append(step)
        self.corrections_count[step] = count

    def skipped(self, step: str, reason: str) -> None:
        self.skipped_steps[step] = reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "applied_steps": self.applied_steps,
            "skipped_steps": self.skipped_steps,
            "corrections_count": self.corrections_count,
            "dropped_elements": self.dropped_elements,
            "warnings": self.warnings,
            "scores": self.scores,
        }


@dataclass
class ParsedDoc:
    """파싱 파이프라인의 산출물. 청킹이 기대는 계약은 전략 문서 §9에 고정돼 있다."""

    doc_id: str                     # 파일 sha256[:16] — 재인덱싱 스킵 판별
    name: str
    profile: Profile
    elements: list[Element]
    meta: dict[str, Any] = field(default_factory=dict)      # C7 승격분
    report: ParseReport = field(default_factory=ParseReport)
    parser_version: str = "docling-2.x+corr-v1"

    def headings(self) -> list[Element]:
        return [e for e in self.elements if e.type in ("heading", "title")]

    def tables(self) -> list[Element]:
        return [e for e in self.elements if e.type == "table"]

    def body(self) -> list[Element]:
        """머리말·꼬리말(furniture)을 뺀 본문 요소."""
        return [e for e in self.elements if e.type not in ("header", "footer")]

    def renumber(self) -> None:
        """`order`를 0..N-1로 다시 매긴다. 요소를 재배열·삭제한 교정 뒤에 호출한다."""
        for i, el in enumerate(self.elements):
            el.order = i
