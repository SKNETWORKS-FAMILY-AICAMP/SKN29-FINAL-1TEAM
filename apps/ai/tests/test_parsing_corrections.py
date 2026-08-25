"""파싱 교정 회귀 테스트 — `pdf_parsing_strategy.md` §7.3.

**docling을 재실행하지 않는다.** `docling_eval/output/layout/layout_result.csv`는 13종
4,561개 요소 전량 덤프이므로, 교정 계층만 이 덤프에 걸어 회귀를 고정한다(docling은 별도
conda 환경과 모델 로딩을 요구해 CI에서 돌리기에 비싸다). 덤프에 문서를 추가하는 경로는
`app/rag/parsing/dump_writer.py`.

교정 단계는 반드시 **적용 전/후 양쪽을 재고** 개선분을 확인한다. 도해 문서 회귀 사고가
바로 이 대조 없이는 보이지 않는다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.rag.parsing import dump, scoring
from app.rag.parsing.corrections import pipeline

from tests.dump_path import find_dump

DUMP_DIR = find_dump() or Path("docling_eval/output")   # None이면 아래 skipif가 잡는다
LAYOUT_CSV = DUMP_DIR / "layout" / "layout_result.csv"
TABLES_DIR = DUMP_DIR / "tables"

pytestmark = pytest.mark.skipif(
    not LAYOUT_CSV.exists(), reason="docling_eval 덤프가 없는 환경"
)

EXPECTED_PROFILE = {
    "법인카드_사용규정": "REGULATION",
    "업무추진비_사용규정": "REGULATION",
    "출장비_사용규정": "REGULATION",
    "회식_운영규정": "REGULATION",
    "법인세법": "LAW",
    "부가가치세법": "LAW",
    "여신전문금융업법": "LAW",
    "부서소개": "DIAGRAM",
    "조직도": "DIAGRAM",
    "직급체계": "DIAGRAM",
    "조직설계_상세기획서": "DIAGRAM",
}


@pytest.fixture(scope="module")
def corrected() -> dict:
    """{문서명: (교정 전 지표, 교정 후 ParsedDoc, 교정 후 지표)}"""
    out = {}
    for name, doc in dump.load_all(LAYOUT_CSV, TABLES_DIR).items():
        before = scoring.measure(doc.elements)
        pipeline.run(doc)
        out[name] = (before, doc, scoring.measure(doc.elements))
    return out


@pytest.mark.parametrize("name,expected", sorted(EXPECTED_PROFILE.items()))
def test_profile_detection(corrected, name, expected):
    """유형 판정이 흔들리면 교정 조합 전체가 바뀐다 — 가장 먼저 고정한다."""
    assert corrected[name][1].profile == expected


@pytest.mark.parametrize("name", sorted(EXPECTED_PROFILE))
def test_chapter_binding_is_trustworthy(corrected, name):
    """C2 — 장·조가 순서대로 서고, 장 안의 조가 빠짐없이 귀속돼야 한다.

    이 계약이 깨지면 `section_path` 메타가 통째로 거짓이 된다(전략 문서 §9).
    """
    after = corrected[name][2]
    assert after["chapters_ordered"], f"{name}: 장 번호가 뒤섞임 {after['chapters']}"
    assert after["articles_ordered"], f"{name}: 조 번호 비단조"


@pytest.mark.parametrize("name", sorted(EXPECTED_PROFILE))
def test_orphan_markers_cleared(corrected, name):
    """C3 — 문단 끝 고아 항/호 마커가 남으면 "제N조 제M항" 인용이 불가능하다."""
    assert corrected[name][2]["orphan_markers"] == 0


@pytest.mark.parametrize("name", ["법인세법", "부가가치세법", "여신전문금융업법"])
def test_circled_clauses_not_auto_numbered(corrected, name):
    """C3(LAW) — 원문자 항에 오름차순 번호가 덧붙는 경로를 전부 끊었는가."""
    before, _, after = corrected[name]
    assert before["auto_numbered_clauses"] > 0, "덤프에 결함이 없으면 테스트가 무의미하다"
    assert after["auto_numbered_clauses"] == 0


@pytest.mark.parametrize("name", sorted(EXPECTED_PROFILE))
def test_spacing_never_regresses(corrected, name):
    """C1 — 완전 복원은 원리상 불가능하다. 요구하는 것은 **악화되지 않을 것**뿐이다."""
    before, _, after = corrected[name]
    assert after["spacing_defects"] <= before["spacing_defects"]


@pytest.mark.parametrize("name", sorted(EXPECTED_PROFILE))
def test_no_content_loss(corrected, name):
    """교정은 내용을 지우지 않는다. 줄어든 요소는 전부 리포트에 사유가 남아야 한다."""
    before, doc, after = corrected[name]
    lost = before["elements"] - after["elements"]
    accounted = len(doc.report.dropped_elements) + doc.report.corrections_count.get("C5", 0)
    assert lost <= accounted, f"{name}: 설명되지 않은 요소 소실 {lost}건"


def test_diagram_plan_excludes_content_destroying_steps(corrected):
    """도해형에 문단 병합·분할 계열을 걸어 80%→53%로 회귀시킨 사고의 재발 방지.

    ⚠️ 이름이 뜻하는 바를 좁게 읽을 것 — 막는 것은 **계층 교정 전반이 아니라 내용을
    파괴할 수 있는 단계**다. C2(기하 재배열)·C3(요소 내 마커 복원)는 요소 경계를 넘지
    않아 허용하고(직급체계에 실제 고아 마커 4건), 금지 목록은 현재 C4 하나다.
    """
    forbidden = {"C4"}
    for name, expected in EXPECTED_PROFILE.items():
        if expected != "DIAGRAM":
            continue
        plan = set(pipeline.PLANS["DIAGRAM"])
        assert not (plan & forbidden), f"도해형 계획에 금지 단계 포함: {plan & forbidden}"
        _, doc, _ = corrected[name]
        for el in doc.elements:
            if el.type == "table":
                assert el.attrs.get("grid") is not None or el.text, f"{name}: 표 내용 소실"


def test_law_toc_dump_removed(corrected):
    """C4 — 목차 덤프 코드블록은 지우되, 지운 사실이 리포트에 남아야 한다."""
    _, doc, _ = corrected["부가가치세법"]
    assert doc.report.corrections_count.get("C4", 0) > 0
    assert doc.report.dropped_elements
    assert all("law_toc" in row for row in doc.report.dropped_elements)


def test_report_explains_every_skipped_step(corrected):
    """건너뛴 단계에는 반드시 사유가 남는다 — 조용한 실패가 최대 위험이다."""
    for _, doc, _ in corrected.values():
        for step, reason in doc.report.skipped_steps.items():
            assert reason, f"{doc.name}: {step} 스킵 사유 없음"


REGULATIONS = [n for n, p in EXPECTED_PROFILE.items() if p == "REGULATION"]


@pytest.mark.parametrize("name", sorted(REGULATIONS))
def test_cover_meta_survives_unrecognized_table(corrected, name):
    """C7 — 표지가 표로 안 잡혀도 시행일을 얻는다.

    📏 docling은 같은 표지 레이아웃을 법인카드·출장비에선 `table`(grid)로, 업무추진비·회식
    에선 개별 `paragraph`로 내놓는다. grid만 보던 구현은 후자 2종에서 `effective_date`를
    통째로 놓쳤다 — 규정 4종이 모두 같은 시행일을 갖는다는 사실이 그 결손을 가려 줬다.
    """
    _, doc, _ = corrected[name]
    assert doc.meta.get("effective_date") == "2026.8.1", (
        f"{name}: 시행일 결측/오값 — {doc.meta.get('effective_date')!r}"
    )
    assert doc.meta.get("enacted_date") == "2026.7.20"
    assert doc.meta.get("owner_dept", "").startswith("경영지원본부")


def test_cover_fallback_rejects_prose(corrected):
    """폴백이 본문 문장을 값으로 집으면 결측보다 나쁘다 — 날짜꼴 가드를 고정한다.

    `revision_history`에서 첫 날짜를 긁는 폴백을 검토했다가 버린 이유가 이것이다:
    업무추진비의 개정이력 첫 날짜는 `2024.1.1`(세법 개정 시행일)이라 규정 시행일이 아니다.
    """
    from app.rag.parsing.corrections import c7_meta
    from app.rag.parsing.model import Element

    def el(text: str, seq: int) -> Element:
        return Element(element_id=f"t:p1:e{seq}", type="paragraph", text=text,
                       page=1, order=seq)

    meta: dict = {}
    c7_meta._cover_pairs(meta, [el("시행일", 1), el("추후 공고한다", 2)])
    assert "effective_date" not in meta

    meta = {}
    c7_meta._cover_pairs(meta, [el("시행일자는 다음과 같다", 1), el("2026. 8. 1.", 2)])
    assert "effective_date" not in meta

    meta = {}
    c7_meta._cover_pairs(meta, [el("시행일", 1), el("2026. 8. 1.", 2)])
    assert meta["effective_date"] == "2026.8.1"
