"""FastMCP 도구 구현 (기술명세서 §5, §5.1).

접근 경로 원칙:
- 관계형 데이터(거래·규정·정산·카드) → Django 내부 read API 경유
- 벡터 데이터(규정/사례 임베딩)     → Chroma 직접
- LLM/Tool은 Postgres에 직접 SQL 금지
스캐폴드: 대부분 stub 반환. TODO 표기.
"""
from __future__ import annotations

import base64
import binascii
import logging

from app.ml.registry import get_active_model

log = logging.getLogger(__name__)


def get_policy(category: str) -> dict:
    """분류별 규정·필요증빙 조회 (Django 경유). Draft/Rule/Risk 공용."""
    return {"category": category, "limit": None, "required_evidence": [], "refs": []}


def get_card_context(card_id: int) -> dict:
    """카드 구분별 필요입력 판정 (Django 경유). Draft."""
    return {"card_id": card_id, "card_type": None, "required_inputs": []}


def search_policy(query: str, filters: dict | None = None) -> dict:
    """규정 청크 RAG 검색 (Chroma 직접). Rule/Risk."""
    return {"query": query, "chunks": []}


def search_cases(query: str) -> dict:
    """유사 과거 승인/반려 사례 검색 (Chroma 직접). Risk."""
    return {"query": query, "similar_cases": []}


def fetch_historical_tx(period: str, filters: dict | None = None) -> dict:
    """과거 거래 로드 (Django 경유). Rule 검증(시뮬레이션)."""
    return {"period": period, "tx": []}


def run_rule_engine(tx: dict, ruleset: str | None = None) -> dict:
    """결정론적 Rule 엔진 실행. Rule 적용(RPA 1차판정)."""
    return {"decision": None, "confidence": 0.0, "hits": []}


def get_tx_features(tx_id: int) -> dict:
    """거래 feature 조립 (Django 경유). Risk 1차 이상탐지 입력."""
    return {"tx_id": tx_id, "feature_vector": []}


def ml_infer(feature_vector: list[float]) -> dict:
    """이상탐지 추론 (MVP: 비지도만). review_prob는 post-MVP."""
    model = get_active_model()
    if not model or not model.fitted:
        return {"anomaly_score": 0.0, "contribs": {}, "note": "no trained model (stub)"}
    return {**model.score(feature_vector), "contribs": {}}


def chunk_pdf(
    filename: str,
    content_base64: str = "",
    path: str = "",
    document_type: str = "regulation",
    include_text: bool = True,
    include_parents: bool = True,
    max_chunks: int = 0,
    target_chars: int = 0,
    max_chars: int = 0,
) -> dict:
    """업로드된 PDF를 파싱·청킹해 RAG 인덱싱 후보 청크를 반환한다.

    파싱 전략: `llm_wiki/_context/pdf_parsing_strategy.md`
    (PyMuPDF 구조·텍스트 + pdfplumber 표 + 임베디드 TOC 1순위, 조(條) 단위 Section-based
     + Parent-Child 청킹, 문자 overlap 0·조상 경로 prepend)

    이 도구는 **청킹까지만** 수행한다. 임베딩·Chroma upsert는 별도 단계이며,
    `quality.passed == False`면 인덱싱하면 안 된다(§13.1⑨ — 나쁜 청크는 지우기 어렵다).

    Args:
        filename: 업로드 파일명. `document_name` 및 출처 표기에 쓰인다.
        content_base64: 업로드 본문(base64). `data:` URI 접두는 제거해도 되고 붙여도 된다.
        path: 컨테이너 내 파일 경로. `content_base64`가 없을 때만 사용(관리자 배치용).
        document_type: `regulation` | `org` | `plan` | `case` | `tax_ref` (§9.1).
        include_text: False면 메타데이터만 반환(대용량 응답 회피).
        include_parents: §8.6 Parent 청크(장 단위, 검색 대상 아님) 포함 여부.
        max_chunks: 0이면 전량. 양수면 앞에서 N개만 반환(미리보기).
        target_chars / max_chars: 0이면 문서별 적응 청킹(§8.3)이 자동 결정.

    Returns:
        `{ok, document, quality, chunking, chunks[], parents[], quarantine[]}`
    """
    # 무거운 파싱 의존성(pymupdf/pdfplumber)은 이 도구를 실제 호출할 때만 로드한다.
    from app.rag.parsing.pipeline import parse_pdf
    from app.rag.parsing.validate import PdfValidationError

    data: bytes | None = None
    if content_base64:
        payload = content_base64.split(",", 1)[-1] if content_base64.startswith("data:") else content_base64
        try:
            data = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            return {"ok": False, "error": f"base64 디코딩 실패: {exc}"}
    elif not path:
        return {"ok": False, "error": "content_base64 또는 path 중 하나는 필요합니다"}

    try:
        result = parse_pdf(
            path=path or None,
            data=data,
            filename=filename or None,
            document_type=document_type,
            target_chars=target_chars or None,
            max_chars=max_chars or None,
        )
    except PdfValidationError as exc:
        # §10.2 케이스 1~3 — 문서 단위 스킵 사유는 조용히 삼키지 않고 그대로 올린다.
        return {"ok": False, "error": str(exc), "stage": "validation"}
    except Exception as exc:  # noqa: BLE001
        log.exception("chunk_pdf 실패: %s", filename or path)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "stage": "parse"}

    def dump(chunks):
        sliced = chunks[:max_chunks] if max_chunks > 0 else chunks
        return [
            {"chunk_id": c.chunk_id, "metadata": c.metadata, **({"text": c.text} if include_text else {})}
            for c in sliced
        ]

    return {
        "ok": True,
        "indexable": result.quality.passed,
        "document": {
            "document_id": result.profile.document_id,
            "document_name": result.profile.document_name,
            "document_type": document_type,
            "source_path": result.profile.source_path,
            "pages": result.profile.page_count,
            "producer": result.profile.producer,
            **result.doc_meta,
        },
        "quality": {
            "passed": result.quality.passed,
            "metrics": result.quality.metrics,
            "issues": result.quality.issues,
        },
        "chunking": result.structure_info,
        "chunks": dump(result.chunks),
        "parents": dump(result.parents) if include_parents else [],
        "quarantine": result.quarantine,
    }
