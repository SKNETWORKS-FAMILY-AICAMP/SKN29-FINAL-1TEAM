"""파싱 배치 엔트리포인트 (관리자 CLI) — `pdf_parsing_strategy.md` §10.

`app/ml/train.py`가 관리자 CLI 배치로 도는 것과 같은 패턴이다. 규정 문서 인덱싱은
관리자 온디맨드 배치이므로 **속도보다 정확도·재현성을 우선**한다.

    # PDF 파싱 (docling 필요)
    python -m app.rag.parsing.index --pdf tiger_inc/pdf/*.pdf --out out/parsed

    # 교정 계층만 재검증 (docling 재실행 없이 기존 덤프에 적용)
    python -m app.rag.parsing.index --dump docling_eval/output --report
"""
from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path

from app.rag.parsing import dump as dump_mod
from app.rag.parsing import scoring
from app.rag.parsing.corrections import pipeline
from app.rag.parsing.model import ParsedDoc


def _serialize(doc: ParsedDoc) -> dict:
    return {
        "doc_id": doc.doc_id,
        "name": doc.name,
        "profile": doc.profile,
        "meta": doc.meta,
        "parser_version": doc.parser_version,
        "report": doc.report.to_dict(),
        "elements": [dataclasses.asdict(el) for el in doc.elements],
    }


def _print_report(name: str, before: dict, doc: ParsedDoc, after: dict) -> None:
    print(f"\n── {name}  [{doc.profile}]")
    print(f"   적용: {doc.report.corrections_count}")
    if doc.report.skipped_steps:
        print(f"   생략: {doc.report.skipped_steps}")
    for key, label in (
        ("spacing_defects", "자간"),
        ("orphan_markers", "고아 마커"),
        ("auto_numbered_clauses", "자동번호 항"),
        ("html_escapes", "HTML escape"),
    ):
        if before[key] or after[key]:
            print(f"   {label:<12} {before[key]:>5} → {after[key]}")
    if not after["chapters_ordered"] or not after["articles_ordered"]:
        print("   ⚠ 장·조 순서 미정합 — 청킹은 조를 최상위로 두어야 한다")
    for warning in doc.report.warnings:
        print(f"   ⚠ {warning}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="PDF 파싱·교정 배치")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--pdf", nargs="+", help="PDF 경로 (docling 실행)")
    src.add_argument("--dump", help="docling_eval/output 경로 (교정만 재실행)")
    ap.add_argument("--out", help="ParsedDoc JSON 출력 디렉터리")
    ap.add_argument("--report", action="store_true", help="교정 전후 지표를 출력")
    args = ap.parse_args(argv)

    docs: dict[str, ParsedDoc] = {}
    metrics: dict[str, tuple[dict, dict]] = {}

    if args.dump:
        root = Path(args.dump)
        loaded = dump_mod.load_all(root / "layout" / "layout_result.csv", root / "tables")
        for name, doc in loaded.items():
            before = scoring.measure(doc.elements)
            pipeline.run(doc)
            docs[name] = doc
            metrics[name] = (before, scoring.measure(doc.elements))
    else:
        from app.rag.parsing import engine

        converters = engine._build_converter()      # 모델 로딩은 한 번만
        for raw in args.pdf:
            for path in sorted(Path().glob(raw)) or [Path(raw)]:
                doc = engine.convert(path, converters)
                before = scoring.measure(doc.elements)
                pipeline.run(doc)
                docs[doc.name] = doc
                metrics[doc.name] = (before, scoring.measure(doc.elements))

    if args.report:
        for name, doc in docs.items():
            _print_report(name, metrics[name][0], doc, metrics[name][1])

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        for name, doc in docs.items():
            (out / f"{name}.json").write_text(
                json.dumps(_serialize(doc), ensure_ascii=False, indent=2), encoding="utf-8"
            )
        print(f"\n{len(docs)}개 문서 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
