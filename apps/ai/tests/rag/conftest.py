"""`tests/rag/` 공용 픽스처.

`sample_regulation.pdf`는 `tests/fixtures/generate_sample_pdf.py`로 만든, 외부
라이브러리 없이 raw PDF 객체를 직접 써서 만든 최소 고정 PDF다(reportlab/fpdf 등이
이 실행 환경에 없어 그렇게 만들었다) — Chapter/Article 헤딩 2단, 본문 문단, 표 1개를
담고 있어 파싱(제목/본문/표 인식)·heading_hierarchy(레벨 분화)·페이지 provenance를
전부 검증할 수 있다.

**한글 조(條) 패턴("제1조")이 아니라 영문("Article 1")을 쓴 이유**: 손으로 짠 PDF에
한글을 넣으려면 CID 폰트를 통째로 임베드해야 하는데(base14 Helvetica는 한글 글리프가
없다) 이 환경엔 그걸 할 라이브러리가 없다. 대신 `app/rag/parsing/profile.py`의
REGULATION 판정은 `제N조` 정규식에 매여 있어, 이 fixture는 REGULATION이 아니라
DIAGRAM/GENERIC으로 분류된다(§ profile.detect 참고) — 그래서 이 테스트들은 프로파일을
하드코딩해서 기대하지 않고 실제 분류 결과를 그대로 쓴다. 한글 조문 텍스트 자체(교정
C1~C7, 조 단위 청킹)의 회귀는 이미 `tests/test_parsing_corrections.py`·
`tests/test_chunking.py`가 `docling_eval/output` 실측 덤프로 촘촘히 커버한다 — 이
스모크 테스트가 새로 커버하는 것은 그 덤프가 건드리지 못하는 부분, 즉 **docling
엔진 자체를 실제로 기동해서** 변환하는 경로(API 호환성·TORCHDYNAMO_DISABLE·백엔드
폴백·heading_hierarchy_options 실동작)다.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")  # noqa: E402 — torch import 이전

import pytest

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
SAMPLE_PDF = FIXTURES_DIR / "sample_regulation.pdf"


def _docling_importable() -> tuple[bool, str]:
    try:
        import docling  # noqa: F401
        from docling.datamodel.pipeline_options import PdfPipelineOptions  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""


DOCLING_OK, DOCLING_IMPORT_ERROR = _docling_importable()

requires_docling = pytest.mark.skipif(
    not DOCLING_OK,
    reason=(
        "docling을 import할 수 없다 — requirements.txt의 docling==2.119.0/"
        f"docling-core==2.91.0 설치를 확인할 것 ({DOCLING_IMPORT_ERROR})"
    ),
)


@pytest.fixture(scope="session")
def sample_pdf_path() -> Path:
    assert SAMPLE_PDF.exists(), f"fixture PDF가 없다: {SAMPLE_PDF} (generate_sample_pdf.py로 생성)"
    return SAMPLE_PDF


@pytest.fixture(scope="session")
def converted_sample_doc(sample_pdf_path: Path):
    """세션당 한 번만 docling을 돌린다 — 모델 로딩이 비싸다(engine.py와 같은 이유)."""
    from app.rag.parsing import engine

    return engine.convert(sample_pdf_path)
