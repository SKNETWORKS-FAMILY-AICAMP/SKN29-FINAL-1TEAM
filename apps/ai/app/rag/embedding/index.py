"""임베딩·적재 배치 엔트리포인트 (관리자 CLI) — `embedding-strategy.md` §8.

파싱·청킹 CLI와 같은 패턴이다. 규정 인덱싱은 관리자 온디맨드 배치이므로 속도보다
**재현성·검증 가능성**을 우선한다.

    # 덤프 → 교정 → 청킹 → 임베딩 → Chroma (docling 재실행 없음)
    python -m app.rag.embedding.index --dump ../../docling_eval/output

    # API를 부르지 않고 무엇이 어디로 갈지만 본다 (권장: 항상 먼저)
    python -m app.rag.embedding.index --dump ../../docling_eval/output --dry-run

    # 적재 결과 확인
    python -m app.rag.embedding.index --peek
"""
from __future__ import annotations

import argparse
from pathlib import Path

from app.rag.chunking.chunker import chunk_document
from app.rag.embedding import config as emb_config
from app.rag.embedding import store
from app.rag.parsing import dump as dump_mod
from app.rag.parsing.corrections import pipeline


def _load_chunks(dump_root: Path, only: list[str] | None):
    docs = dump_mod.load_all(
        dump_root / "layout" / "layout_result.csv", dump_root / "tables"
    )
    chunks, profile_of = [], {}
    for name, doc in docs.items():
        if only and name not in only:
            continue
        pipeline.run(doc)
        got, _ = chunk_document(doc)
        chunks += got
        profile_of[name] = doc.profile
    return chunks, profile_of, docs


def _plan(chunks, profile_of) -> dict[str, dict]:
    """무엇이 어느 컬렉션으로 가는지 — API 호출 전에 눈으로 확인한다."""
    plan: dict[str, dict] = {}
    for chunk in chunks:
        name = store.collection_for(profile_of.get(chunk.doc_name, chunk.profile))
        row = plan.setdefault(name, {"total": 0, "leaves": 0, "docs": set()})
        row["total"] += 1
        row["leaves"] += chunk.chunk_role != "parent"
        row["docs"].add(chunk.doc_name)
    return plan


def main() -> None:
    ap = argparse.ArgumentParser(description="청크 → 임베딩 → Chroma 적재")
    ap.add_argument("--dump", help="파싱 덤프 루트 (docling_eval/output)")
    ap.add_argument("--only", nargs="*", help="문서명 필터")
    ap.add_argument("--dry-run", action="store_true", help="라우팅만 출력, API·Chroma 미사용")
    ap.add_argument("--peek", action="store_true", help="적재 현황만 조회")
    ap.add_argument("--dimensions", type=int, help="차원 재정의 (기본 1024)")
    args = ap.parse_args()

    if args.peek:
        for name in emb_config.ALL_COLLECTIONS:
            try:
                info = store.peek(name)
            except Exception as exc:                        # noqa: BLE001
                print(f"{name:<14} 조회 실패: {type(exc).__name__}: {exc}")
                continue
            print(f"{name:<14}{info['count']:>6}건  {info['embedder_versions']}")
        return

    if not args.dump:
        ap.error("--dump 또는 --peek 중 하나가 필요하다")

    cfg = emb_config.DEFAULT
    if args.dimensions:
        cfg = emb_config.EmbeddingConfig(dimensions=args.dimensions)

    chunks, profile_of, docs = _load_chunks(Path(args.dump), args.only)
    print(f"문서 {len(profile_of)}종 · 청크 {len(chunks):,}개")
    print(f"임베딩 신원  {cfg.version}\n")

    for name, row in sorted(_plan(chunks, profile_of).items()):
        docs_label = ", ".join(sorted(row["docs"]))
        print(f"  {name:<14}{row['total']:>5}청크 (잎 {row['leaves']:>4})  ← {docs_label}")

    missing = [n for n, d in docs.items() if n in profile_of and not d.meta.get("effective_date")
               and d.profile in ("REGULATION", "LAW")]
    if missing:
        print(f"\n⚠ 시행일 결측 {len(missing)}건: {', '.join(missing)} — "
              "이대로 넣으면 시행일 필터가 조용히 어긋난다")

    if args.dry_run:
        print("\n(dry-run — API·Chroma를 호출하지 않았다)")
        return

    print()
    report = store.upsert_chunks(chunks, profile_of, config=cfg)
    for line in report.lines():
        print(line)
    store.assert_single_embedder(sorted(report.per_collection))
    print("\n✅ 임베딩 신원 단일 — 컬렉션에 다른 모델의 벡터가 섞이지 않았다")


if __name__ == "__main__":
    main()
