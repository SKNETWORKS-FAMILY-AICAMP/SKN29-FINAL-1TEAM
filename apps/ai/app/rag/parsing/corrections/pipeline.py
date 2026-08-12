"""교정 파이프라인 — `pdf_parsing_strategy.md` §4.2(프로파일 게이트) · §5.8(실행 순서).

두 가지가 이 모듈의 전부다.

1. **프로파일별로 단계를 켜고 끈다.** 도해 문서에 계층 교정(C2·C3)을 걸었다가 요소
   일치율이 80%→53%로 회귀한 실측 사고가 이 게이트의 근거다. 아래 표에서 빠진 단계는
   "안 해도 되는 것"이 아니라 **하면 안 되는 것**이다.
2. **실행 순서에 의존성이 있다.** 특히 법령의 원문자 항 보존은 C1보다 먼저 와야 한다 —
   NFKC가 ①을 숫자로 뭉개고 나면 항 번호를 복원할 방법이 없다.
"""
from __future__ import annotations

from app.rag.parsing.corrections import (
    c1_spacing, c2_reading_order, c3_markers, c4_law_toc, c5_tables, c6_headings, c7_meta,
)
from app.rag.parsing.model import ParsedDoc, Profile

# 단계 이름은 전략 문서 §5의 C1~C7과 1:1로 맞춘다. 순서가 곧 실행 순서다(§5.8).
PLANS: dict[Profile, tuple[str, ...]] = {
    "REGULATION": ("C1", "C6", "C7", "C3", "C2", "C5"),
    "LAW":        ("C4", "C3", "C1", "C6", "C7", "C2"),
    "DIAGRAM":    ("C1", "C6", "C3", "C2", "C5"),
    "GENERIC":    ("C1", "C6", "C7", "C3", "C2", "C5"),
}

# 프로파일별로 빠진 단계에 남길 사유 — 리포트에서 "왜 안 했는지"가 보여야 한다.
_SKIP_REASON = {
    ("DIAGRAM", "C7"): "도해형 — 문서번호·시행일 체계 없음",
    ("REGULATION", "C4"): "해당 결함 없음(목차 덤프는 법령 전용)",
    ("LAW", "C5"): "해당 결함 없음(법령 3종 표 분할 0건)",
}


def run(doc: ParsedDoc) -> ParsedDoc:
    """교정을 걸고 리포트를 채운다. 요소 리스트는 제자리에서 갱신된다."""
    report = doc.report
    report.profile = doc.profile
    warn = report.warnings.append
    plan = PLANS.get(doc.profile, PLANS["GENERIC"])

    for step in plan:
        if step == "C4":
            report.applied("C4", c4_law_toc.apply(doc.elements, report))
        elif step == "C1":
            report.applied("C1", c1_spacing.apply(doc.elements))
        elif step == "C6":
            report.applied("C6", c6_headings.apply(doc.elements))
        elif step == "C7":
            doc.meta.update(c7_meta.apply(doc.elements))
            report.applied("C7", len(doc.meta))
        elif step == "C3":
            report.applied("C3", c3_markers.apply(doc.elements, doc.profile, warn))
        elif step == "C2":
            report.applied("C2", c2_reading_order.apply(doc.elements, warn))
        elif step == "C5":
            report.applied("C5", c5_tables.apply(doc.elements))

    for step in ("C1", "C2", "C3", "C4", "C5", "C6", "C7"):
        if step not in plan:
            report.skipped(
                step, _SKIP_REASON.get((doc.profile, step), "프로파일 미적용")
            )

    doc.renumber()
    return doc
