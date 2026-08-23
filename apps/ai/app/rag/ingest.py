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
from app.rag.parsing import mock
from app.rag.parsing.corrections import pipeline
from app.rag import triage

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
    clauses: list[dict[str, Any]] = field(default_factory=list)
    # 별표 → 임계값 표 후보(승인 대기). core가 `PolicyTableProposal`로 받는다.
    table_proposals: list[dict[str, Any]] = field(default_factory=list)
    # 분류 단계가 돌았는지·건너뛴 사유. 조용한 누락을 만들지 않기 위해 결과에 남긴다.
    triage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "docId": self.doc_id, "name": self.name, "profile": self.profile,
            "collection": self.collection, "chunkCount": self.chunk_count,
            "leafCount": self.leaf_count, "error": self.error, "warnings": self.warnings,
            "clauses": self.clauses, "tableProposals": self.table_proposals,
            "triage": self.triage,
        }


def build_clauses(chunks) -> tuple[list[dict[str, Any]], int]:
    """청크 → **조(條) 단위** 조항 목록. `(clauses, 조에 안 속한 청크 수)`.

    화면과 사람의 결정 단위는 청크가 아니라 조다. 청킹은 긴 조를 항 단위로 쪼개므로
    (`chunking-strategy` 분할 사다리), 여기서 다시 조로 모은다.

    본문은 **부모(조 전문)가 있으면 그걸** 쓴다 — 잎을 이어 붙이면 항이 잘린 자리의
    문맥이 어긋난다. 부모가 없는 짧은 조는 잎이 곧 조 전문이다.

    조에 속하지 않는 청크(별표 등 조 밖 형제)는 조항 행이 되지 않는다. 검색에는 그대로
    걸리지만 화면 목록에는 안 뜨므로, 몇 개가 그랬는지 세어 돌려준다(조용한 누락 방지).
    """
    by_article: dict[str, dict[str, Any]] = {}
    orphans = 0

    for chunk in chunks:
        label = (chunk.article_label or "").strip()
        if not label:
            orphans += chunk.chunk_role != "parent"
            continue
        row = by_article.setdefault(label, {
            "articleLabel": label,
            "articleNo": chunk.article_no,
            "articleTitle": (chunk.article_title or "").strip(),
            "citation": chunk.citation,
            "body": "",
            "leafBodies": [],
            "pageStart": chunk.page_start,
            "pageEnd": chunk.page_end,
            "chunkIds": [],
        })
        row["chunkIds"].append(chunk.chunk_id)
        row["pageStart"] = min(row["pageStart"], chunk.page_start)
        row["pageEnd"] = max(row["pageEnd"], chunk.page_end)
        if not row["articleTitle"] and chunk.article_title:
            row["articleTitle"] = chunk.article_title.strip()
        if chunk.chunk_role == "parent":
            row["body"] = chunk.text          # 조 전문 — 이게 있으면 이걸 쓴다
        else:
            row["leafBodies"].append(chunk.text)

    clauses = []
    for order, (_, row) in enumerate(
        sorted(by_article.items(), key=lambda kv: (kv[1]["articleNo"] is None, kv[1]["articleNo"] or 0))
    ):
        body = row.pop("body") or "\n\n".join(row["leafBodies"])
        row.pop("leafBodies")
        clauses.append({**row, "body": body, "order": order})
    return clauses, orphans


VALID_PROFILES = {"REGULATION", "LAW", "DIAGRAM", "GENERIC"}


def ingest_pdf(
    pdf_path: str | Path, *, name: str | None = None, profile_hint: str = ""
) -> IngestResult:
    """PDF 하나를 파싱→청킹→임베딩→적재한다. 예외를 삼키지 않고 결과에 담아 돌려준다.

    `doc_id`가 **파일 내용 해시**라, 같은 파일을 다시 넣으면 Chroma에서 같은 ID로 덮어쓴다
    (재색인이 곧 멱등 upsert — 중복 청크가 쌓이지 않는다).
    """
    path = Path(pdf_path)
    if not path.exists():
        return IngestResult(ok=False, name=name or str(path), error=f"파일이 없습니다: {path}")

    # 파싱만 갈아끼우는 지점. 모킹이 꺼져 있으면(기본) 이 분기는 없는 것과 같다.
    # 모킹 실패는 **폴백하지 않고** 그대로 실패시킨다 — 조용히 실물 파싱으로 넘어가면
    # "모킹이 켜졌는데 왜 느리지"를 아무도 모른다.
    mock_warning = ""
    try:
        if mock.enabled():
            doc, mock_warning = mock.parse(path, name=name)
        else:
            doc = engine.convert(path, converters=_get_converters())
    except mock.MockDocumentNotFound as exc:
        logger.warning("docling 모킹 대상 없음 %s: %s", path, exc)
        return IngestResult(ok=False, name=name or path.stem, error=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("파싱 실패 %s", path)
        return IngestResult(ok=False, name=name or path.stem, error=f"파싱 실패: {exc}")

    if name:
        # 표시명은 업로드 제목을 따르되, 청크 메타의 doc_name도 같이 맞춘다 — 검색 결과의
        # citation("「문서명」 제N조")이 화면에 보이는 문서명과 달라지면 근거를 못 찾는다.
        doc.name = name

    # 사람이 지정한 유형이 파서 판정을 이긴다. 교정(pipeline)·청킹이 프로파일별로 갈리므로
    # **교정 전에** 덮어써야 지정이 실제로 반영된다.
    hint = (profile_hint or "").strip().upper()
    if hint in VALID_PROFILES and hint != doc.profile:
        logger.info("문서 유형 지정으로 덮어씀: %s → %s (%s)", doc.profile, hint, doc.name)
        detected, doc.profile = doc.profile, hint
        doc.report.profile = hint
        doc.report.warnings.append(
            f"문서 유형을 지정값 `{hint}`로 처리했다(파서 자동 감지는 `{detected}`)."
        )

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
    clauses, orphans = build_clauses(chunks)

    # ── 분류(triage) — 조항 성격·룰 우선순위 + 별표 → 임계값 표 후보 ──────────
    #  적재가 **끝난 뒤에** 돈다(룰 트리거와 같은 순서 의존은 아니지만, 실패해도 적재를
    #  되돌리지 않으려면 마지막이어야 한다). 예외는 triage 안에서 이미 삼켜진다.
    triage_result = triage.run(
        chunks=chunks, clauses=clauses, collection=collection,
        axis_options=triage.axis_options(), fact_options=triage.fact_paths(),
    )
    for row in clauses:
        row.update(triage_result.clauses.get(row["articleLabel"], {}))
    # 모킹 경고를 **맨 앞에** 둔다 — 화면 경고 배너가 앞쪽 몇 줄만 보여주므로,
    # 뒤에 두면 "이건 실제 파싱 결과가 아니다"라는 사실이 잘려 안 보일 수 있다.
    warnings = ([mock_warning] if mock_warning else [])
    warnings += list(doc.report.warnings) + list(getattr(report, "warnings", []))
    if orphans:
        warnings.append(
            f"조에 속하지 않은 청크 {orphans}개(별표 등) — 검색에는 걸리지만 조항 목록에는 뜨지 않는다."
        )
    if collection not in emb_config.JUDGEMENT_COLLECTIONS:
        # 판정 근거로 인용되지 않는 컬렉션(조직도 등). 올린 사람이 기대와 다를 수 있으니 알린다.
        warnings.append(
            f"이 문서는 `{collection}`에 적재됐다 — 정산 판정은 이 컬렉션을 검색하지 않는다"
            "(조직도·직급체계 등은 판정 근거가 아니다)."
        )

    logger.info("적재 완료 %s → %s (%d청크/잎 %d)", doc.name, collection, upsert.total, leaves)
    if triage_result.skipped_reason:
        warnings.append(triage_result.skipped_reason)
    if triage_result.error:
        warnings.append(f"분류 일부 실패 — {triage_result.error}")

    return IngestResult(
        ok=True, doc_id=doc.doc_id, name=doc.name, profile=doc.profile,
        collection=collection, chunk_count=upsert.total, leaf_count=leaves,
        warnings=warnings[:20], clauses=clauses,
        table_proposals=triage_result.tables, triage=triage_result.to_dict(),
    )
