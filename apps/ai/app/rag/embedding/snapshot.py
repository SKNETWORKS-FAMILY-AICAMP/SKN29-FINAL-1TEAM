"""Chroma 컬렉션 덤프·복원 — **재임베딩 없이** 벡터 DB를 통째로 옮긴다.

    python -m app.rag.embedding.snapshot dump    --out /data/rag_snapshot
    python -m app.rag.embedding.snapshot restore --in  /data/rag_snapshot
    python -m app.rag.embedding.snapshot dump --out ... --collections policy_docs case_history

## 왜 필요한가

지금 벡터 DB를 다시 채우는 방법은 **원문을 다시 파싱·임베딩하는 것뿐**이다
(`app.rag.embedding.index`). 그건 docling 모델 로드에 수십 초, OpenAI 임베딩에 실제 과금이
붙고, 무엇보다 **같은 결과가 나온다는 보장이 없다** — 파서·청커·임베딩 모델이 바뀌면
어제 시연에서 보던 검색 결과가 오늘 달라진다.

시연 데이터를 확정하려면 벡터도 함께 고정돼야 한다. 이 덤프는 **임베딩 벡터를 그대로**
담으므로, 복원할 때 OpenAI를 한 번도 부르지 않는다(과금 0, 재현 100%).

## 무엇을 담나

컬렉션마다 `ids · documents · embeddings · metadatas` 전부. Chroma가 이 넷으로 컬렉션을
재구성한다. `embedder_version`은 메타데이터에 이미 들어 있어(`chunk.to_chroma`) 복원본이
어느 모델로 만든 벡터인지 따라온다.

**JSONL로 쓴다.** 컬렉션 하나가 수천 청크 × 1024차원이라 단일 JSON은 메모리에 통째로
올려야 한다 — 한 줄에 한 청크면 스트리밍으로 읽고 쓴다.

## 복원은 upsert다 (지우지 않는다)

같은 id면 덮어쓰고 없으면 넣는다. **기존 컬렉션을 비우지 않는 이유**: 덤프에 없는 문서가
운영 중에 추가됐을 수 있고, 그걸 조용히 지우면 복구할 방법이 없다. 깨끗한 상태가 필요하면
`--reset`으로 **명시해서** 지운다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterator

from app.rag.embedding.config import JUDGEMENT_COLLECTIONS
from app.rag.embedding.store import get_client, get_collection

#: 덤프 대상 기본값 — 판정에 쓰이는 셋 + 조직 도해.
#  `org_docs`는 판정 경로가 검색하지 않지만(인용 금지) 화면·실험에서는 쓰인다.
DEFAULT_COLLECTIONS = (*JUDGEMENT_COLLECTIONS, "org_docs")

#: 한 번에 읽어 올 청크 수. Chroma `get`은 전량을 메모리에 올리므로 나눠 받는다.
PAGE = 500

MANIFEST = "manifest.json"


def _dump_collection(client, name: str, out_dir: Path) -> dict[str, Any]:
    collection = get_collection(client, name)
    total = collection.count()
    path = out_dir / f"{name}.jsonl"

    written = 0
    with path.open("w", encoding="utf-8") as f:
        for offset in range(0, total, PAGE):
            page = collection.get(
                limit=PAGE, offset=offset,
                include=["documents", "embeddings", "metadatas"],
            )
            #  **`or []`를 쓰지 않는다.** Chroma는 임베딩을 numpy 배열로 돌려주는데,
            #  배열에 `or`를 걸면 "truth value is ambiguous"로 죽는다(실측 2026-08-24).
            #  없을 때만 기본값으로 바꾸도록 `is None`으로 명시한다.
            def _at(key: str, index: int, default):
                seq = page.get(key)
                if seq is None or index >= len(seq):
                    return default
                value = seq[index]
                return default if value is None else value

            ids = page.get("ids")
            ids = [] if ids is None else list(ids)
            for i, cid in enumerate(ids):
                #  임베딩이 없는 행은 **버리지 않고 그대로 남긴다** — 복원 때 그 사실이
                #  드러나야 한다(조용히 빼면 복원본이 원본보다 작은데 아무도 모른다).
                vector = _at("embeddings", i, None)
                f.write(json.dumps({
                    "id": cid,
                    "document": _at("documents", i, ""),
                    "embedding": None if vector is None else [float(x) for x in vector],
                    "metadata": _at("metadatas", i, {}),
                }, ensure_ascii=False) + chr(10))
                written += 1

    return {"collection": name, "count": written, "file": path.name,
            "bytes": path.stat().st_size}


def _read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def dump(out_dir: Path, collections: tuple[str, ...]) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    client = get_client()
    entries = [_dump_collection(client, name, out_dir) for name in collections]
    manifest = {"collections": entries,
                "total": sum(e["count"] for e in entries)}
    (out_dir / MANIFEST).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def restore(in_dir: Path, collections: tuple[str, ...] | None, *, reset: bool) -> dict[str, Any]:
    manifest_path = in_dir / MANIFEST
    if not manifest_path.exists():
        raise SystemExit(f"덤프가 아니다 — {MANIFEST}가 없다: {in_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    client = get_client()

    restored: list[dict[str, Any]] = []
    for entry in manifest["collections"]:
        name = entry["collection"]
        if collections and name not in collections:
            continue
        path = in_dir / entry["file"]
        if not path.exists():
            raise SystemExit(f"덤프 파일이 없다: {path}")

        if reset:
            #  **명시했을 때만** 지운다(모듈 docstring 참조).
            try:
                client.delete_collection(name)
            except Exception:  # noqa: BLE001  # 없으면 그만
                pass
        collection = get_collection(client, name)

        ids, docs, embs, metas, skipped = [], [], [], [], 0

        def flush() -> None:
            if ids:
                collection.upsert(ids=ids, documents=docs, embeddings=embs, metadatas=metas)
                ids.clear(); docs.clear(); embs.clear(); metas.clear()

        for row in _read_jsonl(path):
            if row.get("embedding") is None:
                #  벡터 없는 행은 넣지 않는다 — Chroma가 임베딩 함수 없이 만들어 낼 수
                #  없고(우리 계약이 `embedding_function=None`이다), 넣으면 검색이 죽는다.
                skipped += 1
                continue
            ids.append(row["id"])
            docs.append(row.get("document") or "")
            embs.append(row["embedding"])
            metas.append(row.get("metadata") or {})
            if len(ids) >= PAGE:
                flush()
        flush()

        result = {"collection": name, "restored": entry["count"] - skipped}
        if skipped:
            #  **조용히 넘기지 않는다** — 원본보다 적게 복원됐다는 사실이 보여야 한다.
            result["skipped_no_embedding"] = skipped
        result["now"] = collection.count()
        restored.append(result)

    return {"collections": restored}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chroma 컬렉션 덤프·복원(재임베딩 없음)")
    sub = parser.add_subparsers(dest="command", required=True)

    d = sub.add_parser("dump", help="현재 벡터 DB를 파일로 내린다")
    d.add_argument("--out", required=True, help="덤프를 쓸 디렉터리")
    d.add_argument("--collections", nargs="*", default=None, help=f"기본: {' '.join(DEFAULT_COLLECTIONS)}")

    r = sub.add_parser("restore", help="덤프를 벡터 DB에 되넣는다(upsert)")
    r.add_argument("--in", dest="in_dir", required=True, help="덤프 디렉터리")
    r.add_argument("--collections", nargs="*", default=None, help="일부만 복원할 때")
    r.add_argument("--reset", action="store_true",
                   help="복원 전 대상 컬렉션을 **지운다**. 안 주면 upsert(기존 유지)")

    args = parser.parse_args(argv)
    names = tuple(args.collections) if args.collections else DEFAULT_COLLECTIONS

    if args.command == "dump":
        report = dump(Path(args.out), names)
        for entry in report["collections"]:
            print(f"  {entry['collection']:14s} {entry['count']:6d}건  "
                  f"{entry['bytes'] / 1_048_576:.1f}MB  →  {entry['file']}")
        print(f"덤프 완료 — 총 {report['total']}건 → {args.out}")
    else:
        report = restore(Path(args.in_dir), tuple(args.collections) if args.collections else None,
                         reset=args.reset)
        for entry in report["collections"]:
            extra = (f"  (벡터 없어 건너뜀 {entry['skipped_no_embedding']})"
                     if entry.get("skipped_no_embedding") else "")
            print(f"  {entry['collection']:14s} 복원 {entry['restored']:6d}건 "
                  f"→ 현재 {entry['now']}건{extra}")
        print("복원 완료 — OpenAI 호출 0회(임베딩을 그대로 넣었다)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
