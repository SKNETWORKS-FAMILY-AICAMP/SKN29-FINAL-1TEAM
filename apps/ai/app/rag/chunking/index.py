"""청킹 배치·계측 엔트리포인트 (관리자 CLI) — `chunking-strategy.md` §12.

    # 교정 덤프 → 청크 (docling 재실행 없음, 수초)
    python -m app.rag.chunking.index --dump docling_eval/output --report

    # 실 PDF 경로 (docling 필요 — 별도 conda 환경)
    python -m app.rag.chunking.index --pdf "tiger_inc/pdf/*.pdf" --out out/chunks
"""
from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path

from app.rag.chunking import metrics
from app.rag.chunking.chunker import chunk_document
from app.rag.chunking.model import Budget, Chunk
from app.rag.parsing import dump as dump_mod
from app.rag.parsing.corrections import pipeline
from app.rag.parsing.model import ParsedDoc


def _load(args) -> dict[str, ParsedDoc]:
    if args.dump:
        root = Path(args.dump)
        docs = dump_mod.load_all(root / "layout" / "layout_result.csv", root / "tables")
        for doc in docs.values():
            pipeline.run(doc)
        return docs

    from app.rag.parsing import engine

    converters = engine._build_converter()
    docs: dict[str, ParsedDoc] = {}
    for raw in args.pdf:
        for path in sorted(Path().glob(raw)) or [Path(raw)]:
            doc = engine.convert(path, converters)
            pipeline.run(doc)
            docs[doc.name] = doc
    return docs


def _print(name: str, row: dict, report) -> None:
    print(
        f"{name:<22}{report.profile:<11}"
        f"{row['chunks']:>5}{row['parents']:>6}"
        f"{row['size_median']:>7}{row['size_p90']:>7}{row['size_max']:>7}"
        f"{row['over_max']:>6}{row['tiny']:>6}"
        f"{row['element_coverage']:>8.0%}{row['with_article']:>8.0%}{row['with_chapter']:>8.0%}"
    )
    for warning in report.warnings:
        print(f"   ⚠ {warning}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="구조 기반 청킹 배치")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--pdf", nargs="+")
    src.add_argument("--dump")
    ap.add_argument("--out", help="청크 JSON 출력 디렉터리")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--max", type=int, help="분할 임계 문자수 (기본 1200)")
    ap.add_argument("--target", type=int, help="채우기 목표 문자수 (기본 800)")
    args = ap.parse_args(argv)

    # `--max`만 줬을 때 `target`을 기본값(800)으로 두면 target > max가 되어 채우기 목표가
    # 죽는다. §10.2 스윕과 같은 규약(target = max × 0.67)으로 따라 움직이게 하고, hard도
    # max 아래로 내려가지 않게 올린다 — 어긋나면 `Budget`이 멈춘다.
    budget = Budget()
    if args.max or args.target:
        mx = args.max or budget.max
        budget = Budget(target=args.target or int(mx * 0.67), max=mx,
                        hard=max(budget.hard, mx))

    docs = _load(args)
    rows: dict[str, dict] = {}
    all_chunks: dict[str, list[Chunk]] = {}

    if args.report:
        print(f"{'문서':<22}{'프로파일':<11}{'청크':>5}{'부모':>6}{'중앙':>7}{'p90':>7}"
              f"{'최대':>7}{'초과':>6}{'<100':>6}{'커버':>8}{'조':>8}{'장':>8}")

    for name, doc in docs.items():
        chunks, report = chunk_document(doc, budget)
        rows[name] = metrics.measure(doc, chunks, report, budget)
        all_chunks[name] = chunks
        if args.report:
            _print(name, rows[name], report)

    if args.report:
        total = metrics.summarize(rows)
        print("\n── 코퍼스 요약")
        for key, value in total.items():
            print(f"   {key:<22}{value}")

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        for name, chunks in all_chunks.items():
            (out / f"{name}.json").write_text(
                json.dumps([dataclasses.asdict(c) for c in chunks], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        (out / "_metrics.json").write_text(
            json.dumps({"docs": rows, "summary": metrics.summarize(rows)},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n{len(all_chunks)}개 문서 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
