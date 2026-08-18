"""Docling 파싱 엔진 스모크 테스트 — 실제 PDF·실제 docling 변환.

네트워크·OpenAI·Chroma는 쓰지 않는다. `engine.py`가 실제로 의존하는 두 가지를 검증한다:

1. **설치된 docling 버전이 `engine.py`가 쓰는 API와 실제로 호환되는가**
   (`PdfPipelineOptions.heading_hierarchy_options` — 구버전엔 없어 `AttributeError`로
   죽는다. `apps/ai/scripts/diagnose_docling_env.py` §I와 같은 확인을 pytest로 고정한다).
2. **그 옵션을 켰을 때 실제로 계층이 복원되는가** — 이건 API 존재 여부와 별개 문제였다.
   `engine.py::_to_elements`가 `document.iterate_items()`가 주는 **트리 순회 깊이**를
   `SectionHeaderItem.level`(heading_hierarchy_options가 채우는 실제 필드)로 착각해
   쓰고 있었다 — 옵션은 켜져 있고 API도 존재하는데 모든 헤딩이 조용히 level=1로
   뭉개지는, hasattr()로는 절대 못 잡는 버그였다. 이 파일의 계층 검증 테스트가 그 버그의
   회귀 테스트다.
"""
from __future__ import annotations

from app.rag.parsing.model import ParsedDoc

from tests.rag.conftest import requires_docling


@requires_docling
def test_pdf_pipeline_options_has_heading_hierarchy_options():
    """구버전 docling(<2.106.0)에는 이 필드가 없다 — hasattr()로 우회하지 말고 여기서 드러낸다."""
    from docling.datamodel.pipeline_options import PdfPipelineOptions

    opts = PdfPipelineOptions()
    assert hasattr(opts, "heading_hierarchy_options"), (
        "설치된 docling에 heading_hierarchy_options가 없다 — docling-slim 2.106.0 이상이 "
        "필요하다(apps/ai/requirements.txt의 docling==2.119.0 고정과 실제 설치가 다른지 "
        "`python -m scripts.diagnose_docling_env`로 확인할 것)"
    )
    assert opts.heading_hierarchy_options.enabled is False, "기본값은 꺼짐이어야 한다(명시적으로 켜는 게 계약)"


@requires_docling
def test_build_converter_succeeds_and_enables_heading_hierarchy():
    """`engine._build_converter()`가 실제로 인스턴스를 만들고, 옵션이 켜져 있는지."""
    from app.rag.parsing import engine

    primary, fallback = engine._build_converter()
    assert primary is not None
    assert fallback is not None

    pdf_opts = primary.format_to_options[_pdf_format()].pipeline_options
    assert pdf_opts.heading_hierarchy_options.enabled is True
    assert pdf_opts.do_ocr is False
    assert pdf_opts.do_table_structure is True


def _pdf_format():
    from docling.datamodel.base_models import InputFormat

    return InputFormat.PDF


@requires_docling
def test_convert_sample_pdf_succeeds(converted_sample_doc: ParsedDoc):
    """실제 소형 PDF 1건 변환 성공 — 결과가 비어 있지 않다."""
    assert converted_sample_doc.elements, "변환 결과 요소가 0개다"
    assert converted_sample_doc.doc_id
    assert converted_sample_doc.profile in ("REGULATION", "LAW", "DIAGRAM", "GENERIC")


@requires_docling
def test_title_and_body_text_present(converted_sample_doc: ParsedDoc):
    """제목(헤딩)과 본문 텍스트가 실제로 추출됐는지."""
    headings = [e.text for e in converted_sample_doc.headings()]
    bodies = [e.text for e in converted_sample_doc.elements if e.type == "paragraph"]

    assert any("Chapter 1" in h for h in headings), headings
    assert any("Article 1" in h for h in headings), headings
    assert any("Article 2" in h for h in headings), headings
    assert any("sample provisions for testing" in b for b in bodies), bodies


@requires_docling
def test_table_is_detected_and_preserved(converted_sample_doc: ParsedDoc):
    """fixture의 표(Category/Limit 2x2)가 table 요소로 감지되고 셀 내용이 보존됐는지."""
    tables = converted_sample_doc.tables()
    assert len(tables) >= 1, "fixture에 표가 있는데 하나도 감지되지 않았다"

    table = tables[0]
    assert table.attrs.get("rows", 0) >= 2
    assert table.attrs.get("cols", 0) >= 2
    grid_text = " ".join(cell for row in table.attrs.get("grid", []) for cell in row)
    assert "Category" in grid_text
    assert "Limit" in grid_text
    assert "50000" in grid_text


@requires_docling
def test_page_provenance_present(converted_sample_doc: ParsedDoc):
    """단일 페이지 fixture이므로 모든 요소의 page가 1이어야 한다(0=미상이 아님)."""
    assert converted_sample_doc.elements
    for el in converted_sample_doc.elements:
        assert el.page == 1, f"page provenance 누락/오류: {el.element_id} page={el.page}"


@requires_docling
def test_heading_hierarchy_levels_are_differentiated(converted_sample_doc: ParsedDoc):
    """heading_hierarchy_options.enabled=True가 실제로 계층을 복원하는지 — 이 프로젝트의
    회귀 버그(§ 모듈 docstring)를 정확히 잡는 테스트다.

    "Chapter 1 ..."은 상위 레벨, "Article 1/2 ..."는 그보다 한 단계 아래여야 한다.
    엔진 버그가 있었을 때는 셋 다 level=1로 나왔다(iterate_items의 트리 깊이를 썼기
    때문 — 모든 헤딩이 문서 루트의 형제라 깊이가 같았다).
    """
    headings = {e.text.strip(): e.level for e in converted_sample_doc.headings()}

    chapter_level = next(v for k, v in headings.items() if k.startswith("Chapter 1"))
    article1_level = next(v for k, v in headings.items() if k.startswith("Article 1"))
    article2_level = next(v for k, v in headings.items() if k.startswith("Article 2"))

    assert chapter_level is not None and article1_level is not None
    assert chapter_level < article1_level, (
        f"Chapter(level={chapter_level})가 Article(level={article1_level})보다 상위여야 한다 — "
        "모두 level=1이면 heading_hierarchy_options가 켜졌어도 계층이 반영 안 된 것"
    )
    assert article1_level == article2_level, "같은 종류(Article)는 같은 레벨이어야 한다"


@requires_docling
def test_backend_fallback_pair_are_independent_converters():
    """1순위(pypdfium2)와 폴백(docling-parse 기본 백엔드)이 같은 옵션으로 별도 컨버터인지."""
    from app.rag.parsing import engine

    primary, fallback = engine._build_converter()
    assert primary is not fallback
