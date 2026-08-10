"""Common Document Representation (CDM) — 파싱 전략 §5.1, §13.2.

모든 파서(layout/table/ocr/vlm)의 출력이 이 표현으로 수렴한다.
이 지점 이후(정규화·구조복원·메타·청킹)는 파서가 무엇이었는지 알 필요가 없다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# §9.1 pipeline_version — 파서 로직 변경 시 올려서 선택적 재인덱싱 판별에 쓴다.
PIPELINE_VERSION = "pdf-parse-v1"

ElementType = Literal[
    "title", "heading", "paragraph", "list_item",
    "table", "figure", "caption", "footnote",
    "header", "footer", "page_number", "code_block",
]


@dataclass
class BBox:
    page: int
    x0: float
    y0: float
    x1: float
    y1: float

    def as_meta(self) -> str:
        """§9.1 `bbox` 메타 직렬화 — "p5:72.0,410.5,523.2,588.9"."""
        return f"p{self.page}:{self.x0:.1f},{self.y0:.1f},{self.x1:.1f},{self.y1:.1f}"

    @property
    def area(self) -> float:
        return max(0.0, self.x1 - self.x0) * max(0.0, self.y1 - self.y0)


@dataclass
class DocElement:
    element_id: str            # "{doc_id}:p{page}:e{seq}"
    type: str                  # ElementType
    text: str                  # 정규화 후 텍스트 (표는 Markdown 직렬화)
    bbox: BBox                 # original_location — Citation 근거
    order: int = 0             # 문서 전체 읽기 순서 (전역 단조 증가)
    level: int | None = None   # heading 전용: 1=장, 2=조, 3=항
    parser: str = "layout"     # "layout" | "table" | "ocr" | "vlm"  ← 감사용
    confidence: float = 1.0
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def dense_len(self) -> int:
        """공백 제거 문자수 — §8.2 크기 파라미터의 기준."""
        return len("".join(self.text.split()))


@dataclass
class DocNode:
    """계층 트리 (§5.1). DocElement에서 조립한다."""
    node_id: str
    title: str
    level: int                 # 0=문서 루트, 1=장, 2=조, ...
    path: list[str] = field(default_factory=list)
    elements: list[DocElement] = field(default_factory=list)
    children: list["DocNode"] = field(default_factory=list)
    page_start: int = 0
    page_end: int = 0
    parent: "DocNode | None" = field(default=None, repr=False, compare=False)

    def iter_nodes(self):
        yield self
        for child in self.children:
            yield from child.iter_nodes()

    @property
    def is_leaf(self) -> bool:
        return not self.children


@dataclass
class PageProfile:
    """§4.2 — 라우팅 단위는 문서가 아니라 페이지다."""
    page_no: int
    width: float
    height: float
    char_count: int
    area_ratio_text: float     # 텍스트 bbox 면적 / 페이지 면적
    image_area_ratio: float    # 이미지 bbox 면적 / 페이지 면적
    ctrl_char_ratio: float     # 제어문자 / 전체문자   ← 코퍼스 B가 준 교훈
    ruling_lines: int          # 수평+수직 괘선 수
    col_clusters: int          # x0 클러스터 수 (다단 판정)
    has_toc_anchor: bool = False
    is_duplicate: bool = False


@dataclass
class DocProfile:
    document_id: str
    document_name: str
    source_path: str
    page_count: int
    producer: str
    toc: list[tuple[int, str, int]] = field(default_factory=list)
    body_size: float = 0.0     # 본문 폰트 크기(문자수 가중 최빈값)
    pages: list[PageProfile] = field(default_factory=list)
    encrypted: bool = False
    repaired: bool = False


@dataclass
class Chunk:
    """검색 단위 (§8). `metadata`는 Chroma 규약상 스칼라만 담는다(§9.1)."""
    chunk_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class QualityReport:
    """§9 Quality Validation + §11 지표."""
    passed: bool = True
    metrics: dict[str, Any] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)


@dataclass
class ParseResult:
    profile: DocProfile
    doc_meta: dict[str, Any]
    elements: list[DocElement]
    root: DocNode
    chunks: list[Chunk]              # Child — 임베딩·검색 대상
    parents: list[Chunk]             # Parent — 검색 대상 아님, 컨텍스트 확장용
    quality: QualityReport
    quarantine: list[dict[str, Any]] = field(default_factory=list)
    structure_info: dict[str, Any] = field(default_factory=dict)
