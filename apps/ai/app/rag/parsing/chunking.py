"""⑩ Chunking — 파싱 전략 §8, §13.1⑩.

📏 조문 중앙값 180자 / p90 642 / max 1,199. 여기서 나오는 결론:
조(條)를 원자 단위로 고정하되, **짧은 조는 같은 장(章) 안에서만 병합**하고
**긴 조는 항(項) 경계에서 분할**한다. 문자 overlap은 0 — 대신 조상 경로를 prepend한다.
"""
from __future__ import annotations

import re
import statistics

from app.rag.parsing.model import Chunk, DocElement, DocNode
from app.rag.parsing.metadata import build_metadata
from app.rag.parsing.parsers.tables import MAX_ROWS_PER_CHUNK, to_markdown
from app.rag.parsing.structure import article_no_of

TARGET_DEFAULT = 700          # §8.2 목표(공백 제거 기준)
MAX_DEFAULT = 1000            # §8.2 최대
MIN_CHARS = 120               # §8.2 최소 — 미만이면 형제 조와 병합
ADAPT_MIN, ADAPT_MAX = 400, 1200   # §8.3 적응 범위

_HANG_RE = re.compile(r"(?m)^\s*\d+\.\s")        # 항
_HO_RE = re.compile(r"(?m)^\s*[가-힣]\.\s")      # 호
_SENT_RE = re.compile(r"(?<=[.!?])\s+|(?<=[다요음함임])\.\s+")


def dense(text: str) -> int:
    return len("".join(text.split()))


def adaptive_target(section_lengths: list[int]) -> int:
    """§8.3 — 문서별 리프 섹션 길이 분포로 목표 크기를 조정한다.

    📏 적용 결과: 타이거 규정 → 400(하한), 조직도 → 846, 상세기획서 → 1,200(상한).
    "모든 PDF에 고정 chunk size"는 문서별 중앙값이 6배 차이나는 순간 한쪽을 망친다.
    """
    if not section_lengths:
        return TARGET_DEFAULT
    p90 = statistics.quantiles(section_lengths, n=10)[8] if len(section_lengths) >= 10 else max(section_lengths)
    return max(ADAPT_MIN, min(ADAPT_MAX, int(p90 * 1.1)))


class _Unit:
    """청킹의 원자 단위 = TOC 리프 노드(조)."""

    def __init__(self, node: DocNode):
        self.node = node
        self.body = [e for e in node.elements if e.type != "table"]
        self.tables = [e for e in node.elements if e.type == "table"]
        # 리프(조)는 같은 부모(장) 아래 형제끼리만 병합된다.
        # 비리프 노드가 직접 가진 요소(표지·장 서두)는 `#own`으로 분리해 자식 조와 섞이지 않게 한다.
        self.group_key = (
            node.parent.node_id if (node.is_leaf and node.parent) else f"{node.node_id}#own"
        )

    @property
    def text(self) -> str:
        return "\n".join(e.text for e in self.body).strip()

    @property
    def length(self) -> int:
        return dense(self.text)


def _path_header(path: list[str], doc_no: str = "") -> str:
    """§8.4 — 문자 overlap 대신 조상 경로 prepend.

    (a) 짧은 조문 임베딩이 상위 문맥을 획득, (b) LLM이 조문 번호를 즉시 확보,
    (c) `제9조`로 검색해도 매칭. 📏 경로 40~60자 = 700자 목표 대비 오버헤드 ~8%.
    """
    parts = list(path)
    if doc_no and parts:
        parts[0] = f"{parts[0]}({doc_no})"
    return "[" + " > ".join(parts) + "]"


def _split_text(text: str, max_chars: int) -> list[str]:
    """§8.5 긴 조문 분할: 항 → 호 → 문장. **절대 문장 중간 분할 금지.**"""
    for pattern in (_HANG_RE, _HO_RE):
        marks = [m.start() for m in pattern.finditer(text)]
        if len(marks) >= 2:
            pieces = [text[a:b].strip() for a, b in zip([0, *marks], [*marks, len(text)])]
            pieces = [p for p in pieces if p]
            packed = _pack(pieces, max_chars)
            if all(dense(p) <= max_chars for p in packed) or pattern is _HO_RE:
                return packed
    sentences = [s for s in _SENT_RE.split(text) if s.strip()]
    if len(sentences) >= 2:
        return _pack(sentences, max_chars)
    # §10.2 케이스 12 — 문장 경계도 없으면 하드 분할(호출부에서 hard_split 마킹).
    return [text[i:i + max_chars * 2] for i in range(0, len(text), max_chars * 2)]


def _pack(pieces: list[str], max_chars: int) -> list[str]:
    out: list[str] = []
    cur = ""
    for piece in pieces:
        candidate = f"{cur}\n{piece}".strip() if cur else piece
        if cur and dense(candidate) > max_chars:
            out.append(cur)
            cur = piece
        else:
            cur = candidate
    if cur:
        out.append(cur)
    return out


def _split_table_grid(el: DocElement) -> list[str]:
    """§8.5 — 표는 분할하지 않는다. 40행 초과 시에만 헤더 행을 반복하며 분할."""
    grid = el.attrs.get("grid") or []
    if len(grid) <= MAX_ROWS_PER_CHUNK:
        return [el.text]
    header, rows = grid[0], grid[1:]
    out = []
    for i in range(0, len(rows), MAX_ROWS_PER_CHUNK - 1):
        out.append(to_markdown([header, *rows[i:i + MAX_ROWS_PER_CHUNK - 1]]))
    return out


def chunk_document(
    root: DocNode,
    *,
    document_id: str,
    document_name: str,
    document_type: str,
    source_path: str,
    doc_meta: dict,
    target: int | None = None,
    max_chars: int | None = None,
    min_chars: int = MIN_CHARS,
) -> tuple[list[Chunk], list[Chunk], dict]:
    units = [_Unit(n) for n in root.iter_nodes() if n.elements]
    target = target or adaptive_target([u.length for u in units if u.length])
    max_chars = max_chars or max(MAX_DEFAULT, int(target * 1.3))
    doc_no = doc_meta.get("doc_no", "")

    # ── 같은 장(章) 안에서만 형제 조를 그리디 병합. 장을 넘는 병합은 금지(§8.2).
    groups: list[list[_Unit]] = []
    for unit in units:
        if (
            groups
            and groups[-1][-1].group_key == unit.group_key
            and dense(" ".join(u.text for u in [*groups[-1], unit])) <= target
        ):
            groups[-1].append(unit)
        else:
            groups.append([unit])

    # ── 최소 크기 미달(§8.2 120자) 잔여 그룹은 목표를 넘더라도 같은 장의 형제와 합친다.
    #    임베딩이 문맥을 못 잡는 파편 청크를 남기지 않기 위한 2차 패스다.
    merged: list[list[_Unit]] = []
    for group in groups:
        body_len = dense(" ".join(u.text for u in group))
        has_table = any(u.tables for u in group)
        if (
            merged
            and 0 < body_len < min_chars
            and not has_table
            and merged[-1][-1].group_key == group[0].group_key
            and dense(" ".join(u.text for u in [*merged[-1], *group])) <= max_chars
        ):
            merged[-1].extend(group)
        else:
            merged.append(group)
    groups = merged

    chunks: list[Chunk] = []
    order = 0

    def emit(
        text: str,
        unit: _Unit,
        element_type: str,
        part: int,
        parts: int,
        extra: dict,
        pages: tuple[int, int] | None = None,
    ) -> None:
        nonlocal order
        node = unit.node
        parent_node = node.parent if node.parent else root
        suffix = f":p{part}" if parts > 1 else ""
        chunk_id = f"{node.node_id}:{element_type[0]}{order}{suffix}"
        # Citation은 청크가 실제로 걸친 페이지여야 한다 — 노드 범위(장 전체)가 아니다.
        page_start, page_end = pages or (node.page_start, node.page_end)
        meta = build_metadata(
            document_id=document_id,
            document_name=document_name,
            document_type=document_type,
            source_path=source_path,
            doc_meta=doc_meta,
            chunk_id=chunk_id,
            parent_id=parent_node.node_id if parent_node is not root else root.node_id,
            element_type=element_type,
            page_start=page_start,
            page_end=page_end,
            section_path=" > ".join(node.path[1:]) or node.title,
            section=node.path[1] if len(node.path) > 1 else node.title,
            subsection=node.path[2] if len(node.path) > 2 else (node.title if len(node.path) > 1 else ""),
            article_no=article_no_of(node.title),
            heading_level=max(1, node.level),
            order=order,
            char_len=dense(text),
            extra={**extra, **({"part": f"{part}/{parts}"} if parts > 1 else {})},
        )
        chunks.append(Chunk(chunk_id=chunk_id, text=text, metadata=meta))
        order += 1

    for group in groups:
        head = group[0]
        header_node = head.node if len(group) == 1 else (head.node.parent or root)
        header = _path_header(header_node.path, doc_no)

        # 본문 청크
        bodies: list[str] = []
        for unit in group:
            if not unit.text:
                continue
            title = unit.node.title if len(group) > 1 and unit.node is not header_node else ""
            bodies.append(f"{title}\n{unit.text}".strip() if title else unit.text)
        body_text = "\n\n".join(bodies).strip()

        if body_text:
            no_split = any(e.attrs.get("no_split") for u in group for e in u.body)
            # 조상 경로 prepend 분량까지 포함해 최대 크기를 지킨다(char_len은 실제 임베딩 텍스트 기준).
            budget = max(200, max_chars - dense(header))
            parts = [body_text] if (dense(body_text) <= budget or no_split) else _split_text(body_text, budget)
            truncated = any(e.attrs.get("truncated") for u in group for e in u.body)
            confidences = [e.confidence for u in group for e in u.body] or [1.0]
            body_pages = [e.bbox.page for u in group for e in u.body]
            page_span = (min(body_pages), max(body_pages)) if body_pages else None
            for i, part_text in enumerate(parts, start=1):
                emit(
                    f"{header}\n\n{part_text}",
                    head,
                    "paragraph",
                    i,
                    len(parts),
                    {
                        "parser": "layout",
                        "parse_confidence": min(confidences),
                        "merged_sections": [u.node.title for u in group] if len(group) > 1 else [],
                        # 표지·서두는 본문 섹션이 아니다 — 길이 지표에서 분리해 판정한다.
                        "is_front_matter": head.node.level == 0 or None,
                        "truncated": truncated or None,
                        "no_split": no_split or None,
                        "bbox": group[0].body[0].bbox.as_meta() if group[0].body else "",
                    },
                    pages=page_span,
                )

        # 표 청크 — 표 1개 = 청크 1개(분할 안 함). 조상 경로 + 캡션 prepend(§7.1.3)
        for unit in group:
            for el in unit.tables:
                caption = el.attrs.get("caption") or unit.node.title
                pieces = _split_table_grid(el)
                for i, piece in enumerate(pieces, start=1):
                    emit(
                        f"{_path_header(unit.node.path, doc_no)}\n{caption}\n\n{piece}",
                        unit,
                        "table",
                        i,
                        len(pieces),
                        {
                            "parser": el.parser,
                            "parse_confidence": el.confidence,
                            "table_rows": el.attrs.get("rows"),
                            "table_cols": el.attrs.get("cols"),
                            "continued_from": el.attrs.get("continued_from"),
                            "page_span": el.attrs.get("page_span"),
                            "bbox": el.bbox.as_meta(),
                        },
                        pages=tuple(el.attrs.get("page_span") or (el.bbox.page, el.bbox.page)),
                    )

    # ── §8.6 Parent 청크: 장(章) 전체. 검색 대상 아님, 히트 시 컨텍스트 확장용.
    parents: list[Chunk] = []
    for node in root.iter_nodes():
        if node.level != 1 or not any(n.elements for n in node.iter_nodes()):
            continue
        sections = []
        for n in node.iter_nodes():
            if not n.elements:
                continue
            body = "\n".join(e.text for e in n.elements)
            sections.append(f"{n.title}\n{body}".strip())
        text = "\n\n".join(sections)
        meta = build_metadata(
            document_id=document_id,
            document_name=document_name,
            document_type=document_type,
            source_path=source_path,
            doc_meta=doc_meta,
            chunk_id=node.node_id,
            parent_id=root.node_id,
            element_type="section",
            page_start=node.page_start,
            page_end=node.page_end,
            section_path=" > ".join(node.path[1:]) or node.title,
            section=node.title,
            article_no=article_no_of(node.title),
            heading_level=1,
            order=len(parents),
            char_len=dense(text),
            extra={"is_parent": True},
        )
        parents.append(Chunk(chunk_id=node.node_id, text=f"{_path_header(node.path, doc_no)}\n\n{text}", metadata=meta))

    info = {
        "target_chars": target,
        "max_chars": max_chars,
        "min_chars": min_chars,
        "units": len(units),
        "groups": len(groups),
    }
    return chunks, parents, info
