"""청킹 내재 품질 계측 — `chunking-strategy.md` §10.

**검색 성능 평가(Recall@K 등)는 여기 없다.** 임베딩 모델이 미확정이고 질의 정답셋도
아직 없기 때문이다(§11 결정대기 ①·②). 지어낸 점수를 내놓느니 임베딩 없이도 측정 가능한
것만 재고, 나머지는 미측정으로 남긴다 — 파싱 전략의 "정답 없는 항목은 점수화 금지"와
같은 규칙이다.

여기서 재는 6종은 전부 **청크만 보고 판정 가능한 것**이다.
"""
from __future__ import annotations

import statistics as st

from app.rag.chunking.model import Budget, Chunk, ChunkReport, DEFAULT_BUDGET
from app.rag.parsing.model import ParsedDoc


def _pct(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


def measure(doc: ParsedDoc, chunks: list[Chunk], report: ChunkReport,
            budget: Budget = DEFAULT_BUDGET) -> dict[str, object]:
    """청크 열 하나에 대한 지표 묶음."""
    leaves = [c for c in chunks if c.chunk_role != "parent"]
    sizes = [c.size for c in leaves] or [0]
    body_ids = {e.element_id for e in doc.body()
                if e.text.strip() and not e.attrs.get("dropped")}
    owned = {eid for c in chunks for eid in c.element_ids}
    dup = sum(len(c.element_ids) for c in chunks) - len(owned)
    # 헤더 문자열로만 실린 요소(장 헤딩)는 소유가 아니라 참조로 센다 — 유실은 아니다.
    covered = owned | {eid for c in chunks for eid in c.context_element_ids}

    tables = [c for c in leaves if c.has_table]
    split_tables = [c for c in tables if "table_row_split" in c.flags]

    return {
        "chunks": len(chunks),
        "leaves": len(leaves),
        "parents": len(chunks) - len(leaves),
        # ① 크기 분포 — 검색 적합성
        "size_min": min(sizes), "size_median": int(st.median(sizes)),
        "size_p90": sorted(sizes)[int(len(sizes) * 0.9) - 1] if sizes else 0,
        "size_max": max(sizes),
        "over_max": sum(1 for s in sizes if s > budget.max),
        "over_hard": sum(1 for s in sizes if s > budget.hard),
        "tiny": sum(1 for s in sizes if s < 100),
        # ② 요소 커버리지 — 의미 단위 유실 여부 (0이어야 한다)
        "element_coverage": _pct(len(covered & body_ids), len(body_ids)),
        "uncovered": len(body_ids - covered),
        "duplicated_elements": dup,
        # ③ 계층 보존 — 청크만 보고 소속을 알 수 있는가
        "with_article": _pct(sum(1 for c in leaves if c.article_label), len(leaves)),
        "with_chapter": _pct(sum(1 for c in leaves if c.chapter_title), len(leaves)),
        "with_citation": _pct(sum(1 for c in leaves if c.citation), len(leaves)),
        "with_header": _pct(sum(1 for c in leaves if c.header), len(leaves)),
        # ④ 경계 품질 — 강제 분할은 문장을 끊는다
        "hard_split": sum(1 for c in leaves if "hard_split" in c.flags),
        "clause_splits": report.splits.get("clause", 0),
        # ⑤ 표 무결성 — 표가 다른 텍스트와 섞이지 않았는가
        "tables": len(tables),
        "tables_row_split": len(split_tables),
        "tables_mixed": sum(1 for c in tables if len(c.element_ids) > 1),
        # ⑥ 인용 신뢰도 · 노이즈
        "marker_uncertain": sum(1 for c in leaves if "marker_uncertain" in c.flags),
        "toc_like": sum(1 for c in leaves if "toc_like" in c.flags),
        "parent_children_linked": all(
            c.parent_chunk_id for c in leaves if c.chunk_role == "child"
        ),
    }


def summarize(rows: dict[str, dict[str, object]]) -> dict[str, object]:
    """문서별 지표 → 코퍼스 요약. 비율은 문서 수 평균이 아니라 청크 수 가중으로 낸다."""
    leaves = sum(int(r["leaves"]) for r in rows.values()) or 1
    def weighted(key: str) -> float:
        return round(sum(float(r[key]) * int(r["leaves"]) for r in rows.values()) / leaves, 4)

    return {
        "docs": len(rows),
        "chunks": sum(int(r["chunks"]) for r in rows.values()),
        "leaves": leaves,
        "parents": sum(int(r["parents"]) for r in rows.values()),
        "over_max": sum(int(r["over_max"]) for r in rows.values()),
        "over_hard": sum(int(r["over_hard"]) for r in rows.values()),
        "tiny": sum(int(r["tiny"]) for r in rows.values()),
        "uncovered": sum(int(r["uncovered"]) for r in rows.values()),
        "duplicated_elements": sum(int(r["duplicated_elements"]) for r in rows.values()),
        "hard_split": sum(int(r["hard_split"]) for r in rows.values()),
        "toc_like": sum(int(r["toc_like"]) for r in rows.values()),
        "marker_uncertain": sum(int(r["marker_uncertain"]) for r in rows.values()),
        "tables": sum(int(r["tables"]) for r in rows.values()),
        "element_coverage": weighted("element_coverage"),
        "with_article": weighted("with_article"),
        "with_chapter": weighted("with_chapter"),
        "with_citation": weighted("with_citation"),
    }
