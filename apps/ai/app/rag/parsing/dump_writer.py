"""`ParsedDoc` 덤프 **쓰기** — `dump.py`의 역방향. 신규 문서를 모킹 대상에 추가한다.

`DOCLING_MOCK=1`은 `docling_eval/output`에 이미 있는 문서만 처리한다(이름 정확 일치).
새 규정을 모킹으로 돌려보려면 **docling을 한 번은 진짜로 태워** 그 산출물을 덤프에
넣어야 하는데, 그 산출물을 만들던 코드가 평가 노트북(`docling_parsing_test.ipynb`)
셀 안에만 있었다. 노트북은 전 코퍼스를 재실행하는 물건이라 문서 2종을 얹는 데 쓸 수 없다.

    # 컨테이너에서 (docling 필요). --out은 **쓰기 가능한** 경로여야 한다 —
    # compose가 /data/docling_eval을 :ro로 마운트하므로 거기엔 못 쓴다.
    python -m app.rag.parsing.dump_writer \
        --pdf /tmp/pdf/회의비_사용규정.pdf /tmp/pdf/식대_사용규정.pdf \
        --out /tmp/dump/output

## 덤프는 교정 **전** 상태다

`ingest_pdf()`는 파싱 결과를 받아 `corrections.pipeline.run()`을 건다. 덤프에 교정 후
텍스트를 넣으면 모킹 경로에서만 교정이 두 번 걸린다. 그래서 여기서는 `engine.convert()`가
아니라 docling 원본을 그대로 직렬화한다(`index.py --pdf`가 교정까지 돌려 `parsed/*.json`을
쓰는 것과 **다른 목적**이다).

## 순회 범위가 운영과 다른 이유

노트북이 만든 기존 4,388행은 `BODY + FURNITURE`를 순회했다(머리말·꼬리말 인식률도 재려고).
운영 `engine._to_elements()`는 기본 순회라 `BODY`만 본다. 여기서는 **기존 덤프와 같은
범위**를 쓴다 — 같은 CSV에 두 규칙이 섞이면 문서별로 Header/Footer 유무가 갈린다.
그 차이는 하류에서 흡수된다: `ParsedDoc.body()`가 header/footer를 걷어내고, 청킹은
body만 본다.

## 병합은 문서 단위 교체다

같은 문서를 다시 태우면 기존 행을 **지우고** 새로 넣는다(append 아님). 안 그러면 재실행이
행을 두 배로 만들고, `load_all()`이 Order 중복으로 조용히 뒤섞인 문서를 내놓는다.

⚠️ 평가 산출물(`summary.csv`·`hierarchy/`·`chunking/`·`evaluation/`)은 **건드리지 않는다.**
그건 11종 코퍼스를 채점한 스냅샷(Overall 89.3)이고, 신규 문서를 끼워 넣으면 채점 대상과
채점 결과가 어긋난다. 여기서 쓰는 건 런타임 입력(`layout/`·`tables/`·`markdown/`)뿐이다.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path

os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")   # noqa: E402 — engine.py와 같은 이유

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

LAYOUT_COLUMNS = [
    "Document", "Order", "Page", "Element Type", "Docling Label",
    "Level", "Depth", "Marker", "BBox (l,t,r,b)", "Chars", "Text",
]
TABLE_COLUMNS = [
    "Document", "Table", "Page", "Rows", "Cols", "Cells", "Header", "Header Rows",
    "Multi Header", "Row Header", "Merged Cells", "Empty Cells", "Fill Rate",
    "Caption", "Note",
]

# docling 원본 라벨 → 덤프의 화면 집계용 타입. `dump._TYPE_MAP`이 이걸 되돌려 읽으므로
# **양쪽이 같은 어휘**여야 한다(여기 없는 라벨은 "Other"로 나가고 로더가 버린다).
ELEMENT_GROUP = {
    "title": "Title", "section_header": "Heading",
    "text": "Text", "paragraph": "Text",
    "list_item": "List",
    "table": "Table", "document_index": "Table",
    "picture": "Picture", "chart": "Picture",
    "caption": "Caption", "footnote": "Footnote",
    "page_header": "Header", "page_footer": "Footer",
    "formula": "Formula", "code": "Code", "reference": "Reference",
    "form": "Form", "key_value_region": "Form",
}


def _element_text(item, doc) -> str:
    """표는 자리표시자만 남긴다 — 격자·Markdown은 `tables/<문서>/table_NN.json`이 갖는다."""
    from docling_core.types.doc.document import TableItem

    if isinstance(item, TableItem):
        return item.caption_text(doc) or f"<table {item.data.num_rows}x{item.data.num_cols}>"
    text = getattr(item, "text", None)
    if text:
        return " ".join(text.split())
    label = getattr(getattr(item, "label", None), "value", "item")
    return f"<{label}>"


def _heading_level(item, label: str) -> str:
    from docling_core.types.doc.document import SectionHeaderItem

    if isinstance(item, SectionHeaderItem):
        return f"H{item.level}"
    return "H1" if label == "title" else ""


def collect_layout(name: str, doc) -> list[dict]:
    """DoclingDocument → `layout_result.csv` 행. 노트북 셀 8과 같은 규칙이다."""
    from docling_core.types.doc import ContentLayer
    from docling_core.types.doc.document import ListItem

    rows: list[dict] = []
    items = doc.iterate_items(
        with_groups=False,
        included_content_layers={ContentLayer.BODY, ContentLayer.FURNITURE},
    )
    for order, (item, depth) in enumerate(items, start=1):
        label = getattr(getattr(item, "label", None), "value", None)
        if label is None:               # 라벨 없는 컨테이너 노드
            continue
        prov = list(getattr(item, "prov", None) or [])
        bbox = prov[0].bbox if prov else None
        text = _element_text(item, doc)
        rows.append({
            "Document": name,
            "Order": order,
            "Page": prov[0].page_no if prov else "",
            "Element Type": ELEMENT_GROUP.get(label, "Other"),
            "Docling Label": label,
            "Level": _heading_level(item, label),
            "Depth": depth,
            "Marker": (getattr(item, "marker", "") or "") if isinstance(item, ListItem) else "",
            "BBox (l,t,r,b)": (
                f"{bbox.l:.1f},{bbox.t:.1f},{bbox.r:.1f},{bbox.b:.1f}" if bbox else ""
            ),
            "Chars": len(text),
            "Text": text,
        })
    return rows


def _table_info(name: str, doc, idx: int, table) -> dict:
    data = table.data
    cells = list(data.table_cells or [])
    header_cells = [c for c in cells if c.column_header]
    merged = [c for c in cells if (c.row_span or 1) > 1 or (c.col_span or 1) > 1]
    empty = [c for c in cells if not (c.text or "").strip()]
    header_rows = sorted({c.start_row_offset_idx for c in header_cells})
    prov = list(table.prov or [])
    return {
        "Document": name, "Table": idx,
        "Page": prov[0].page_no if prov else "",
        "Rows": data.num_rows, "Cols": data.num_cols, "Cells": len(cells),
        "Header": "Detected" if header_cells else "Not detected",
        "Header Rows": len(header_rows),
        "Multi Header": "Y" if len(header_rows) > 1 else "N",
        "Row Header": "Y" if any(c.row_header for c in cells) else "N",
        "Merged Cells": len(merged),
        "Empty Cells": len(empty),
        "Fill Rate": round(1 - len(empty) / len(cells), 3) if cells else 0.0,
        "Caption": (table.caption_text(doc) or "")[:60],
        # 표 영역은 잡았는데 셀이 0개 = 구조 복원 실패. 그냥 두면 Rows/Cols 0이 조용히 묻힌다.
        "Note": "" if cells else "표 영역만 검출 · 셀 구조 복원 실패 (0x0)",
    }


def write_tables(name: str, doc, tables_dir: Path) -> list[dict]:
    """`tables/<문서>/table_NN.{json,csv}`. 파일명 순서 = 문서 내 표 순서(로더가 zip한다)."""
    infos: list[dict] = []
    out_dir = tables_dir / name
    if out_dir.is_dir():                      # 표가 줄어든 재실행에서 옛 파일이 남지 않게
        for stale in out_dir.glob("table_*"):
            stale.unlink()
    if not doc.tables:
        return infos
    out_dir.mkdir(parents=True, exist_ok=True)

    for idx, table in enumerate(doc.tables, start=1):
        info = _table_info(name, doc, idx, table)
        stem = out_dir / f"table_{idx:02d}"
        try:
            table.export_to_dataframe(doc).to_csv(
                stem.with_suffix(".csv"), index=False, encoding="utf-8-sig"
            )
        except Exception as exc:  # noqa: BLE001 — 표 하나가 깨져도 나머지는 진행
            info["Note"] = f"DataFrame 변환 실패: {type(exc).__name__}: {exc}"[:120]
        try:
            markdown_table = table.export_to_markdown(doc)
        except Exception as exc:  # noqa: BLE001
            markdown_table = ""
            info["Note"] = (info["Note"] + f" | Markdown 실패: {type(exc).__name__}").strip(" |")

        payload = dict(info)
        payload["cells"] = [
            {
                "row": c.start_row_offset_idx, "col": c.start_col_offset_idx,
                "row_span": c.row_span, "col_span": c.col_span,
                "column_header": c.column_header, "row_header": c.row_header,
                "text": c.text,
            }
            for c in (table.data.table_cells or [])
        ]
        payload["markdown"] = markdown_table
        stem.with_suffix(".json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        infos.append(info)
    return infos


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _merge(existing: list[dict], fresh: list[dict], names: set[str]) -> list[dict]:
    """문서 단위 교체 — 이번에 태운 문서의 옛 행을 걷어내고 새 행을 뒤에 붙인다."""
    return [r for r in existing if r.get("Document") not in names] + fresh


def _rebuild_aggregates(layout_rows: list[dict], layout_dir: Path) -> None:
    """`layout_by_document`·`layout_by_page`는 전부 파생이라 통째로 다시 만든다."""
    types = sorted({r["Element Type"] for r in layout_rows})
    per_doc: dict[str, Counter] = {}
    for row in layout_rows:
        per_doc.setdefault(row["Document"], Counter())[row["Element Type"]] += 1

    total = Counter()
    for counter in per_doc.values():
        total.update(counter)
    # pandas crosstab(margins=True).sort_index()의 출력 순서 — ALL이 한글 문서명보다 앞선다.
    by_doc = [{"Document": "ALL", **{t: total[t] for t in types}, "ALL": sum(total.values())}]
    for name in sorted(per_doc):
        counter = per_doc[name]
        by_doc.append(
            {"Document": name, **{t: counter[t] for t in types}, "ALL": sum(counter.values())}
        )
    _write_csv(layout_dir / "layout_by_document.csv", ["Document", *types, "ALL"], by_doc)

    per_page: Counter = Counter()
    for row in layout_rows:
        per_page[(row["Document"], str(row["Page"]), row["Element Type"])] += 1
    _write_csv(
        layout_dir / "layout_by_page.csv",
        ["Document", "Page", "Element Type", "Count"],
        [
            {"Document": d, "Page": p, "Element Type": t, "Count": c}
            for (d, p, t), c in sorted(
                per_page.items(), key=lambda kv: (kv[0][0], int(kv[0][1] or 0), kv[0][2])
            )
        ],
    )


def add_documents(pdf_paths: list[Path], out_root: Path) -> dict[str, dict]:
    """PDF들을 docling으로 태워 `out_root`(=`docling_eval/output`) 덤프에 병합한다."""
    from docling.datamodel.base_models import ConversionStatus

    from app.rag.parsing import engine

    primary, fallback = engine._build_converter()       # 운영과 같은 파이프라인 옵션
    layout_dir, tables_dir, md_dir = (
        out_root / "layout", out_root / "tables", out_root / "markdown"
    )

    fresh_layout: list[dict] = []
    fresh_tables: list[dict] = []
    report: dict[str, dict] = {}

    for pdf in pdf_paths:
        name = pdf.stem
        document = used = None
        for label, converter in (("pypdfium2", primary), ("docling-parse", fallback)):
            try:
                res = converter.convert(pdf)
            except Exception as exc:  # noqa: BLE001 — 백엔드별 예외를 모아 폴백한다
                report.setdefault(name, {}).setdefault("warnings", []).append(
                    f"{label}: {type(exc).__name__}: {exc}"[:200]
                )
                continue
            if res.status in (ConversionStatus.SUCCESS, ConversionStatus.PARTIAL_SUCCESS):
                document, used = res.document, label
                break
            report.setdefault(name, {}).setdefault("warnings", []).append(
                f"{label}: status={res.status.value}"
            )
        if document is None:
            report.setdefault(name, {})["ok"] = False
            continue

        rows = collect_layout(name, document)
        fresh_layout.extend(rows)
        fresh_tables.extend(write_tables(name, document, tables_dir))

        md_dir.mkdir(parents=True, exist_ok=True)
        try:
            (md_dir / f"{name}.md").write_text(document.export_to_markdown(), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 — Markdown은 부가 산출물이다
            report.setdefault(name, {}).setdefault("warnings", []).append(
                f"markdown: {type(exc).__name__}: {exc}"[:200]
            )

        report.setdefault(name, {}).update({
            "ok": True, "backend": used, "pages": document.num_pages(),
            "elements": len(rows), "tables": len(document.tables or []),
        })

    names = {p.stem for p in pdf_paths}
    layout_csv = layout_dir / "layout_result.csv"
    merged_layout = _merge(_read_csv(layout_csv), fresh_layout, names)
    _write_csv(layout_csv, LAYOUT_COLUMNS, merged_layout)
    _rebuild_aggregates(merged_layout, layout_dir)

    summary_csv = tables_dir / "table_summary.csv"
    _write_csv(
        summary_csv, TABLE_COLUMNS, _merge(_read_csv(summary_csv), fresh_tables, names)
    )
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="신규 문서를 docling 덤프(모킹 대상)에 추가")
    ap.add_argument("--pdf", nargs="+", required=True, help="PDF 경로")
    ap.add_argument("--out", required=True, help="docling_eval/output 경로 (쓰기 가능해야 한다)")
    args = ap.parse_args(argv)

    paths = [Path(p) for p in args.pdf]
    missing = [p for p in paths if not p.is_file()]
    if missing:
        print(f"[error] 파일이 없다: {', '.join(str(p) for p in missing)}")
        return 1

    report = add_documents(paths, Path(args.out))
    failed = 0
    for name, info in report.items():
        if info.get("ok"):
            print(
                f"[ok]   {name}  pages={info['pages']}  elements={info['elements']}"
                f"  tables={info['tables']}  backend={info['backend']}"
            )
        else:
            failed += 1
            print(f"[fail] {name}")
        for warning in info.get("warnings", []):
            print(f"       ⚠ {warning}")
    print(f"\n{len(report) - failed}/{len(paths)}건 → {args.out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
