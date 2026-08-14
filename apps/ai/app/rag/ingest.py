"""규정 문서 적재 파이프라인 — PDF 한 개를 Chroma까지 넣는 **유일한 함수**.

    PDF ─► 파싱(docling) ─► 교정(C1~C7) ─► 청킹(조 단위) ─► 임베딩 ─► Chroma upsert

각 단계는 이미 있었지만 서로 **디스크의 파일로만 이어져 있었다**: 파싱 CLI가 JSON을
떨구고 임베딩 CLI가 그 JSON을 읽는 구조라, 업로드된 파일 하나를 끝까지 밀어 넣을 방법이
없었다. 여기가 그 이음매다. 각 단계의 로직은 그대로 두고 호출만 한다 — 사본을 만들면
CLI 경로와 업로드 경로의 적재 결과가 조용히 갈라진다.

**컬렉션 라우팅은 프로파일이 정한다**(`embedding/config.COLLECTION_OF`): 규정→`policy_docs`,
법령→`tax_refs`, 도해→`org_docs`. 조직도가 판정 근거로 인용되면 안 되므로 판정 경로는
`org_docs`를 검색하지 않는다 — 그 분리가 여기서 지켜진다.

**모델 로딩이 비싸다**: docling 컨버터는 프로세스당 한 번만 만들고 재사용한다.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.rag.chunking.chunker import chunk_document
from app.rag.embedding import config as emb_config
from app.rag.embedding import store
from app.rag.parsing import engine
from app.rag.parsing.corrections import pipeline

logger = logging.getLogger(__name__)

# docling 컨버터는 모델을 올린다(수 초~수십 초). 문서마다 만들면 적재가 몇 배 느려진다.
_converters = None
_converter_lock = threading.Lock()


def _get_converters():
    global _converters
    with _converter_lock:
        if _converters is None:
            _converters = engine._build_converter()
        return _converters


@dataclass
class IngestResult:
    """적재 결과 — 성공/실패 어느 쪽이든 **왜 그런지**가 담긴다."""
    ok: bool
    doc_id: str = ""
    name: str = ""
    profile: str = ""
    collection: str = ""
    chunk_count: int = 0
    leaf_count: int = 0
    error: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "docId": self.doc_id, "name": self.name, "profile": self.profile,
            "collection": self.collection, "chunkCount": self.chunk_count,
            "leafCount": self.leaf_count, "error": self.error, "warnings": self.warnings,
        }


def ingest_pdf(pdf_path: str | Path, *, name: str | None = None) -> IngestResult:
    """PDF 하나를 파싱→청킹→임베딩→적재한다. 예외를 삼키지 않고 결과에 담아 돌려준다.

    `doc_id`가 **파일 내용 해시**라, 같은 파일을 다시 넣으면 Chroma에서 같은 ID로 덮어쓴다
    (재색인이 곧 멱등 upsert — 중복 청크가 쌓이지 않는다).
    """
    path = Path(pdf_path)
    if not path.exists():
        return IngestResult(ok=False, name=name or str(path), error=f"파일이 없습니다: {path}")

    try:
        doc = engine.convert(path, converters=_get_converters())
    except Exception as exc:  # noqa: BLE001
        logger.exception("파싱 실패 %s", path)
        return IngestResult(ok=False, name=name or path.stem, error=f"파싱 실패: {exc}")

    if name:
        # 표시명은 업로드 제목을 따르되, 청크 메타의 doc_name도 같이 맞춘다 — 검색 결과의
        # citation("「문서명」 제N조")이 화면에 보이는 문서명과 달라지면 근거를 못 찾는다.
        doc.name = name

    try:
        pipeline.run(doc)                       # 교정 C1~C7 (프로파일별 계획)
        chunks, report = chunk_document(doc)
    except Exception as exc:  # noqa: BLE001
        logger.exception("청킹 실패 %s", path)
        return IngestResult(ok=False, name=doc.name, doc_id=doc.doc_id,
                            profile=doc.profile, error=f"청킹 실패: {exc}")

    if not chunks:
        return IngestResult(
            ok=False, name=doc.name, doc_id=doc.doc_id, profile=doc.profile,
            error="청크가 0개입니다 — 텍스트 레이어가 없는 스캔 PDF일 수 있습니다(현재 OCR 미사용).",
            warnings=list(doc.report.warnings),
        )

    try:
        collection = store.collection_for(doc.profile)
        upsert = store.upsert_chunks(chunks, {doc.name: doc.profile})
    except Exception as exc:  # noqa: BLE001
        logger.exception("적재 실패 %s", path)
        return IngestResult(ok=False, name=doc.name, doc_id=doc.doc_id, profile=doc.profile,
                            error=f"임베딩·적재 실패: {exc}")

    leaves = sum(1 for c in chunks if c.chunk_role != "parent")
    warnings = list(doc.report.warnings) + list(getattr(report, "warnings", []))
    if collection not in emb_config.JUDGEMENT_COLLECTIONS:
        # 판정 근거로 인용되지 않는 컬렉션(조직도 등). 올린 사람이 기대와 다를 수 있으니 알린다.
        warnings.append(
            f"이 문서는 `{collection}`에 적재됐다 — 정산 판정은 이 컬렉션을 검색하지 않는다"
            "(조직도·직급체계 등은 판정 근거가 아니다)."
        )

    logger.info("적재 완료 %s → %s (%d청크/잎 %d)", doc.name, collection, upsert.total, leaves)
    return IngestResult(
        ok=True, doc_id=doc.doc_id, name=doc.name, profile=doc.profile,
        collection=collection, chunk_count=upsert.total, leaf_count=leaves,
        warnings=warnings[:20],
    )
