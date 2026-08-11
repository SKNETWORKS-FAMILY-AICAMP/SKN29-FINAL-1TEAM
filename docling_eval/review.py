# -*- coding: utf-8 -*-
"""정답지 없는 문서(law/ 법령 등)의 후처리 품질을 **사람이 검수**하기 위한 시트 생성기.

`tiger_inc/md/`에 원본이 있는 규정 8종은 `postprocess.score_line_joins()`로 자동
채점이 되지만, `tiger_inc/law/`의 법령 3종은 정답지가 없다. 그래서 점수를 내는
대신 **후처리가 내린 판정을 전수 기록**해서 눈으로 확인할 수 있게 한다.

생성물 (`output/review/<문서명>/`):

| 파일 | 내용 | 봐야 할 것 |
|---|---|---|
| `summary.md` | 후처리 건수 + 규칙별 분포 | weak 비율이 높으면 R4를 믿지 말 것 |
| `linebreaks.csv` | R4 줄바꿈 판정 **전수** | `confidence=weak` 행부터. `decision`이 맞는지 |
| `linebreaks_weak.csv` | 위에서 weak만 추림 | 여기부터 보면 된다 |
| `merges.csv` | R3가 붙인 요소 쌍 | 별개 조문·목을 붙였는지 |
| `splits.csv` | R6이 쪼갠 항목 | 잘못 쪼갰는지 |
| `markers.csv` | R2가 복원한 순번 | 엉뚱한 번호가 붙었는지 |
| `reorder.csv` | R1이 옮긴 요소 | 순서가 실제로 나아졌는지 |
| `unmatched.csv` | 원본에서 위치를 못 찾은 요소 | R4가 그냥 통과시킨 것들 |
| `elements.csv` | 최종 요소 목록 | 전체 훑기 |
| `result.md` | 최종 Markdown | RAG에 들어갈 실제 텍스트 |

사용:
    python review.py                          # law/ 3종 전부
    python review.py 법인세법                  # 이름으로 하나만
    python review.py 법인세법 --steps R1,R4,R5  # R3 끄고 비교
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import DocItemLabel, ListItem, TableItem

import postprocess as pp

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
TIGER = REPO_ROOT / "tiger_inc"
FURNITURE = (DocItemLabel.PAGE_HEADER, DocItemLabel.PAGE_FOOTER)


# --------------------------------------------------------------------------- #
def build_converter() -> DocumentConverter:
    """노트북 §3과 동일한 파이프라인 설정."""
    options = PdfPipelineOptions()
    options.do_table_structure = True
    options.table_structure_options.do_cell_matching = True
    options.do_ocr = False
    options.heading_hierarchy_options.enabled = True
    fmt = PdfFormatOption(pipeline_options=options)
    fmt.backend = PyPdfiumDocumentBackend
    return DocumentConverter(format_options={InputFormat.PDF: fmt})


def write_csv(path: Path, header: list[str], rows: list) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(header)
        writer.writerows(rows)


def _page(item) -> int | None:
    prov = getattr(item, "prov", None) or []
    return prov[0].page_no if prov else None


def _text(item) -> str:
    if isinstance(item, TableItem):
        return f"<table {item.data.num_rows}x{item.data.num_cols}>"
    return " ".join((getattr(item, "text", "") or "").split())


# --------------------------------------------------------------------------- #
def build_review(pdf_path: Path, out_root: Path, vocab_paths=None, steps=None) -> dict:
    """한 문서를 변환·후처리하고 검수 시트를 만든다. 요약 dict를 돌려준다."""
    pdf_path = Path(pdf_path)
    out_dir = out_root / pdf_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = build_converter().convert(pdf_path).document
    pages = pp.read_raw_pages(pdf_path)
    vocab_paths = list(vocab_paths or [pdf_path])
    vocab = pp.build_vocabulary(vocab_paths)
    on = set(pp.REPAIR_ORDER) if steps is None else set(steps)

    # ---- 단계별 스냅샷 (순서는 postprocess.REPAIR_ORDER 와 동일해야 한다) ----
    order_before = [ref.cref for ref in doc.body.children]
    snap = {id(t): t.text for t in doc.texts}
    live = {id(t) for t in doc.texts}

    markers = pp.repair_list_markers(doc) if "R2" in on else 0
    marker_rows = [
        [_page(t), t.marker, _text(t)]
        for t in doc.texts
        if isinstance(t, ListItem) and (t.marker or "").strip() and snap.get(id(t)) != t.text
    ]

    pre_merge = {id(t): t.text for t in doc.texts}
    merges = pp.repair_split_items(doc, pages) if "R3" in on else 0
    merge_rows = []
    for t in doc.texts:
        old = pre_merge.get(id(t))
        if old is not None and t.text != old and t.text.startswith(old):
            merge_rows.append([_page(t), old[-60:], t.text[len(old):][:60], _text(t)[:200]])
    dropped = live - {id(t) for t in doc.texts}

    joins, missed = pp.repair_line_joins(doc, pages, vocab) if "R4" in on else (0, 0)
    spacing = pp.repair_letter_spacing(doc, pages) if "R5" in on else 0

    pre_split = {id(t) for t in doc.texts}
    splits = pp.repair_embedded_markers(doc) if "R6" in on else 0
    split_rows = [
        [_page(t), t.marker, _text(t)[:160]] for t in doc.texts if id(t) not in pre_split
    ]

    moved = pp.repair_reading_order(doc) if "R1" in on else 0
    order_after = [ref.cref for ref in doc.body.children]
    pos_before = {cref: i for i, cref in enumerate(order_before)}
    reorder_rows = [
        [i, pos_before.get(cref, ""), _page(ref.resolve(doc)), _text(ref.resolve(doc))[:90]]
        for i, (cref, ref) in enumerate(zip(order_after, doc.body.children))
        if pos_before.get(cref) != i
    ]

    # ---- R4 판정 전수 재현 (결정론적이라 같은 결과가 나온다) ----
    line_rows, rule_counts = [], {}
    for item in doc.texts:
        if item.label in FURNITURE:
            continue
        page = _page(item)
        if page not in pages:
            continue
        raw_slice = pages[page].locate(item.text)
        if raw_slice is None:
            continue
        trace: list = []
        pp.rejoin_lines(raw_slice, vocab, trace=trace)
        for tail, head, join, rule in trace:
            confidence = pp.RULE_CONFIDENCE.get(rule, "-")
            rule_counts[rule] = rule_counts.get(rule, 0) + 1
            line_rows.append([
                page, rule, confidence,
                "붙임" if join else "띄움",
                tail, head,
                f"{tail}{'' if join else ' '}{head}",
                _text(item)[:70],
            ])

    unmatched_rows = []
    for item in doc.texts:
        if item.label in FURNITURE:
            continue
        page = _page(item)
        if page in pages and pages[page].locate(item.text) is None:
            unmatched_rows.append([page, item.label.value, _text(item)[:160]])

    element_rows = [
        [i, _page(it), it.label.value if hasattr(it, "label") else "",
         getattr(it, "marker", "") or "", _text(it)]
        for i, (it, _d) in enumerate(doc.iterate_items(with_groups=False), start=1)
        if hasattr(it, "label")
    ]

    # ---- 파일로 ----
    write_csv(out_dir / "linebreaks.csv",
              ["page", "rule", "confidence", "decision", "tail", "head", "result", "element"],
              line_rows)
    write_csv(out_dir / "linebreaks_weak.csv",
              ["page", "rule", "confidence", "decision", "tail", "head", "result", "element"],
              [r for r in line_rows if r[2] == "weak"])
    write_csv(out_dir / "merges.csv", ["page", "앞조각_끝", "붙인_조각", "병합결과"], merge_rows)
    write_csv(out_dir / "splits.csv", ["page", "marker", "쪼갠_결과"], split_rows)
    write_csv(out_dir / "markers.csv", ["page", "marker", "text"], marker_rows)
    write_csv(out_dir / "reorder.csv", ["새_위치", "이전_위치", "page", "text"], reorder_rows)
    write_csv(out_dir / "unmatched.csv", ["page", "label", "text"], unmatched_rows)
    write_csv(out_dir / "elements.csv", ["order", "page", "label", "marker", "text"], element_rows)
    (out_dir / "result.md").write_text(doc.export_to_markdown(), encoding="utf-8")

    weak = sum(n for r, n in rule_counts.items() if pp.RULE_CONFIDENCE.get(r) == "weak")
    total = sum(rule_counts.values())
    summary = {
        "문서": pdf_path.stem,
        "페이지": doc.num_pages(),
        "요소": len(element_rows),
        "steps": "+".join(s for s in pp.REPAIR_ORDER if s in on),
        "R1_reordered": moved,
        "R2_markers_restored": markers,
        "R3_items_merged": merges,
        "R3_items_dropped": len(dropped),
        "R4_texts_rejoined": joins,
        "R4_unmatched": missed,
        "R5_letter_spacing": spacing,
        "R6_items_split": splits,
        "줄바꿈_판정": total,
        "근거없음(weak)": weak,
        "weak_비율": f"{weak / total * 100:.0f}%" if total else "-",
        "vocab": len(vocab),
    }

    lines = [f"# {pdf_path.stem} 후처리 검수 요약", "", "| 항목 | 값 |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in summary.items()]
    lines += ["", "## 줄바꿈 판정 규칙 분포", "", "| 규칙 | 신뢰도 | 건수 |", "|---|---|---|"]
    for rule, n in sorted(rule_counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {rule} | {pp.RULE_CONFIDENCE.get(rule, '-')} | {n} |")
    lines += [
        "", "## 검수 순서", "",
        "1. `merges.csv` — R3가 별개 조문·목을 붙였는지. **법령은 여기서 오작동이 확인됨.**",
        "2. `linebreaks_weak.csv` — 근거 없이 찍은 줄바꿈 판정. `decision`이 맞는지.",
        "3. `unmatched.csv` — 원본 대조에 실패해 R4가 손대지 못한 요소.",
        "4. `result.md` — 최종 텍스트를 원문 PDF와 나란히 놓고 확인.",
    ]
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="법령 등 정답지 없는 문서의 후처리 검수 시트 생성")
    parser.add_argument("names", nargs="*", help="문서 이름(확장자 없이). 생략하면 law/ 전체")
    parser.add_argument("--steps", default=None,
                        help="적용할 교정 단계 (예: R1,R4,R5). 생략하면 전부")
    parser.add_argument("--out", default=None, help="출력 폴더 (기본 output/review)")
    args = parser.parse_args(argv)

    steps = [s.strip().upper() for s in args.steps.split(",")] if args.steps else None
    out_root = Path(args.out) if args.out else BASE_DIR / "output" / "review"

    candidates = sorted((TIGER / "law").glob("*.pdf")) + sorted((TIGER / "pdf").glob("*.pdf"))
    if args.names:
        wanted = set(args.names)
        targets = [p for p in candidates if p.stem in wanted]
        missing = wanted - {p.stem for p in targets}
        if missing:
            print(f"찾을 수 없음: {', '.join(sorted(missing))}", file=sys.stderr)
            print("가능한 이름: " + ", ".join(p.stem for p in candidates), file=sys.stderr)
            return 1
    else:
        targets = sorted((TIGER / "law").glob("*.pdf"))

    # 어휘 사전은 규정+법령 전체에서 만든다 (법령 어휘를 담으려면 law/도 필요)
    vocab_paths = sorted((TIGER / "pdf").glob("*.pdf")) + sorted((TIGER / "law").glob("*.pdf"))

    summaries = []
    for pdf in targets:
        print(f"[{pdf.stem}] 변환·후처리 중 …", flush=True)
        summaries.append(build_review(pdf, out_root, vocab_paths=vocab_paths, steps=steps))

    keys = ["문서", "페이지", "요소", "R3_items_merged", "R4_unmatched", "줄바꿈_판정", "weak_비율"]
    widths = [max(len(str(s[k])) for s in summaries + [{k: k for k in keys}]) for k in keys]
    print()
    print("  ".join(k.ljust(w) for k, w in zip(keys, widths)))
    for s in summaries:
        print("  ".join(str(s[k]).ljust(w) for k, w in zip(keys, widths)))
    print(f"\n검수 시트 -> {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
