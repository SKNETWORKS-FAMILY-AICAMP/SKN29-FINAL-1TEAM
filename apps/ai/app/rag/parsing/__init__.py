"""PDF 파싱 파이프라인 — `llm_wiki/_context/pdf_parsing_strategy.md`.

engine(docling) → profile(유형 판정) → corrections(C1~C7) → ParsedDoc.
청킹이 기대는 계약은 전략 문서 §9에 고정돼 있다.
"""
from app.rag.parsing.model import Element, ParsedDoc, ParseReport, Profile

__all__ = ["Element", "ParsedDoc", "ParseReport", "Profile", "parse", "parse_dump"]


def parse(pdf_path, converters=None) -> ParsedDoc:
    """운영 경로: PDF → 교정 완료된 ParsedDoc."""
    from app.rag.parsing import engine
    from app.rag.parsing.corrections import pipeline

    return pipeline.run(engine.convert(pdf_path, converters))


def parse_dump(layout_csv, tables_dir=None) -> dict[str, ParsedDoc]:
    """검증 경로: docling_eval 덤프 → 교정 완료된 ParsedDoc 묶음 (docling 재실행 없음)."""
    from app.rag.parsing import dump
    from app.rag.parsing.corrections import pipeline

    return {
        name: pipeline.run(doc)
        for name, doc in dump.load_all(layout_csv, tables_dir).items()
    }
