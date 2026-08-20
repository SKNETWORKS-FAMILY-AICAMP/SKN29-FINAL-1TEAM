"""FastMCP 도구 구현 (기술명세서 §5, §5.1).

접근 경로 원칙:
- 관계형 데이터(거래·규정·정산·카드) → Django 내부 read API 경유
- 벡터 데이터(규정/사례 임베딩)     → Chroma 직접
- LLM/Tool은 Postgres에 직접 SQL 금지
스캐폴드: 대부분 stub 반환. TODO 표기.
"""
from __future__ import annotations

import logging

import pandas as pd

from app.clients import core_client
from app.ml import features as ml_features
from app.ml.registry import get_active_model

logger = logging.getLogger(__name__)


def get_policy(category: str) -> dict:
    """분류별 규정·필요증빙 조회 (Django 경유, `PolicyLookupView`). Draft/Rule/Risk 공용.

    Django 미기동·네트워크 오류 등으로 조회에 실패하면 예외를 그대로 올린다 —
    호출부(Draft Agent 등)가 각자의 폴백 정책으로 처리한다(결정론적 폴백은 여기서 감추지 않는다).
    """
    data = core_client.get_policy(category)
    return {
        "category": data.get("category", category),
        "limit": data.get("limit_amount"),
        "required_evidence": data.get("required_evidence", []),
        "tax_note": data.get("tax_note", ""),
        "refs": data.get("refs", []),
    }


def get_card_context(card_id: int) -> dict:
    """카드 구분별 필요입력 판정 (Django 경유). Draft."""
    return {"card_id": card_id, "card_type": None, "required_inputs": []}


def classify_merchant(merchant: str, place_hint: str | None = None) -> dict:
    """가맹점 업종 판별 — 캐시→카카오→LLM 재분류 캐스케이드 (§7-1). Draft, Risk 공용 Tool.

    구현 실체는 `app.merchant.classify` — 카카오 원시 카테고리를 그대로 쓰지 않고 LLM이
    **정본 업종 어휘**(core `domain/transactions/industry.py`의 미러 `app/schemas.py`)로
    재분류한다. 카카오에서도 못 찾으면 예외 없이 미확정(industry_code/label 공란)을 돌려준다.

    Draft Agent가 초안 작성 **전에** 이 tool을 부른다(`agents/draft_agent._resolve_industry`) —
    업종은 분류 판단의 입력이라 뒤에 붙이면 표시용밖에 안 된다. Risk 연동은 아직 없다.
    """
    from app.merchant.classify import classify as _classify

    result = _classify(merchant, place_hint)
    return {"merchant": merchant, **result}


def search_policy(
    query: str,
    top_k: int = 6,
    include_law: bool = False,
    filters: dict | None = None,
    rerank: bool = False,
) -> dict:
    """규정 청크 RAG 검색 (Chroma 직접). Rule/Risk 공용 tool.

    구현 실체는 `agents/rule_agent_v0/search.py` — 그쪽이 팀 RAG 정본
    (`rag/embedding/store.search`, `policy_docs` 운영 인덱스)을 부모 필터·부모 확장·컬렉션
    라우팅까지 그대로 쓴다. `agents/rule_agent_v0/vector_store.py`는 격리된 로컬 실험
    스토어라 여기서 쓰지 않는다(승격하면 2차 검증이 빈 결과만 도는 죽은 경로가 된다).
    Risk Review Agent도 **이 tool을 거쳐** 같은 검색 경로·로깅을 공유해야 한다(§5).

    `rerank=True`면 벡터 top-k 대신 LLM이 질의에 실제로 답하는 후보만 추린다
    (`rag/retrieval/rerank.py`) — Rule Agent가 tool-calling 중 근거가 부정확하다고
    판단하면 직접 켤 수 있고, Risk Review 2차 검증은 항상 켠 채로 부른다.

    조회 실패는 감추지 않고 올린다 — 빈 결과와 장애를 구분해야 "규정이 아직 안 실렸다"와
    "Chroma가 죽었다"를 화면에서 가려낼 수 있다.
    """
    from app.agents.rule_agent_v0.search import search_policy as _search

    hits = _search(query, top_k=top_k, include_law=include_law, rerank=rerank)
    if filters:
        hits = [h for h in hits if all(h.get("metadata", {}).get(k) == v for k, v in filters.items())]
    logger.info("search_policy q=%r top_k=%d rerank=%s hits=%d", query, top_k, rerank, len(hits))
    return {"query": query, "chunks": hits}


def read_receipt(file_ref: str) -> dict:
    """영수증(사진·캡처·PDF 전표) 판독 → 사용내역 + 판정 사실. Draft (FR-DA-02).

    별도 OCR 엔진 없이 비전 모델이 이미지에서 바로 필드를 뽑는다(기술명세서 §2).
    총액뿐 아니라 **품목**을 읽는 이유는 거기서만 나오는 판정 사실이 있어서다
    (주류 포함 여부 → `dining.includes_alcohol`, 지출 세부유형 → `category.item_type`).

    실패는 폴백으로 덮지 않는다 — 초안이 조용히 빈 값으로 채워지면 사용자가 "AI가 읽었다"고
    믿고 그대로 제출한다.
    """
    from app.vision import read_receipt as _read

    result = _read(file_ref)
    logger.info("read_receipt %s → facts %d개, 경고 %d건",
                file_ref, len(result["extracted"]), len(result["warnings"]))
    return result


def read_evidence_document(file_ref: str, kind: str) -> dict:
    """증빙 문서(사전승인·회의록·참석자명단·출장계획서) 판독 → 판정 사실. Risk/Rule.

    출력이 `Attachment.extracted`/`field_confidence`/`evidence_spans`와 **같은 모양**이라
    Django가 변환 없이 저장하고, 조립기가 그대로 EvalContext에 얹는다.

    **관측 계약**: 경로가 있으면 관측한 것, 없으면 안 본 것이다(→ `None` → 미해소 가드).
    「확인했는데 없음」을 「안 봤음」과 섞지 않는 것이 이 도구의 핵심이다.
    """
    from app.vision import read_evidence_document as _read

    result = _read(file_ref, kind)
    logger.info("read_evidence_document %s kind=%s → %s, facts %d개",
                file_ref, kind, result["extraction_status"], len(result["extracted"]))
    return result


def search_cases(query: str) -> dict:
    """유사 과거 승인/반려 사례 검색 (Chroma 직접, `case_history`). Risk.

    `case_history`는 아직 실 결정이력 적재 파이프라인이 없다(post-MVP) — 비어 있으면
    `app/rag/case_store.py`가 빈 리스트를 돌려주고, 호출부는 그걸 "근거 없음"으로 다뤄야
    한다(임의로 지어내지 않는다).
    """
    from app.rag.case_store import search_cases as _search_cases

    hits = _search_cases(query, top_k=5)
    similar_cases = [
        {
            "case_id": h["case_id"],
            "citation": h.get("metadata", {}).get("citation") or h["case_id"],
            "outcome": h.get("metadata", {}).get("outcome", ""),
            "text": h["text"],
            "score": h["score"],
        }
        for h in hits
    ]
    return {"query": query, "similar_cases": similar_cases}


def fetch_historical_tx(period: str, filters: dict | None = None) -> dict:
    """과거 거래 로드 (Django 경유). Rule 검증(시뮬레이션)."""
    return {"period": period, "tx": []}


def build_rule_context(settlement_id: int) -> dict:
    """판정용 EvalContext(facts 스냅샷) 조립 (Django 경유, `RuleContextView`). Rule(적용).

    별표 룩업·ORM 조회는 Django의 조립기가 전부 끝낸다. `unresolved_policy_fields`가
    비어 있지 않으면 그 필드를 참조하는 룰은 판정을 신뢰할 수 없다(엔진이 REVIEW로 강등).
    """
    return core_client.build_rule_context(settlement_id)


def run_rule_engine(settlement_id: int) -> dict:
    """결정론적 Rule 엔진 실행 — RPA 1차판정 (Django 경유).

    엔진 실체는 Django `policies/engine.py`(순수함수)이고, 그래프 선택·`rule_hits` 기록·
    상태 전이는 `policies/orchestrator.py`+`settlements/services.judge`가 한 트랜잭션으로
    묶는다. 셋 다 Postgres를 쓰므로 FastAPI는 위임만 한다(§5.1: 관계형은 Django 경유).

    반환은 정산 상세 + `ruleResult`(decision·path·flags·그래프별 내역).
    """
    return core_client.judge_settlement(settlement_id)


def get_tx_features(tx_id: int) -> dict:
    """거래 feature 조립 (Django 경유 + 원-핫 인코딩). Risk 1차 이상탐지 입력.

    관계형 조회(카드별 과거 거래 집계)는 Django `build_tx_features`가 전부 끝낸다 — 여기서는
    그 결과(15개 원본 피처, 행 1건)를 학습과 동일한 `app.ml.features.build_feature_matrix`로
    변환하고, 활성 모델이 있으면 그 `feature_columns` 순서에 맞춰 정렬한다.
    """
    raw = core_client.get_tx_features(tx_id)["features"]
    df = pd.DataFrame([raw])

    model = get_active_model()
    fill_values = pd.Series(model.fill_values) if (model and model.fill_values) else pd.Series(dtype=float)
    X = ml_features.build_feature_matrix(df, fill_values)

    if model and model.feature_columns:
        X = ml_features.align_to_model(X, model.feature_columns)

    return {"tx_id": tx_id, "feature_vector": X.iloc[0].astype(float).tolist()}


def ml_infer(feature_vector: list[float]) -> dict:
    """이상탐지 추론 (MVP: 비지도만). review_prob는 post-MVP.

    형상 검증: 빈 벡터나 학습된 model.feature_columns와 길이가 다른 벡터를 조용히 잘못된 점수로
    흘려보내지 않는다 — get_tx_features 쪽 구현이 어긋났을 때 여기서 바로 드러나야 한다.
    """
    model = get_active_model()
    if not model or not model.fitted:
        return {"anomaly_score": 0.0, "contribs": {}, "note": "no trained model (stub)"}
    if not feature_vector:
        raise ValueError("ml_infer: feature_vector가 비어 있습니다 — get_tx_features 결과를 확인하세요.")
    if model.feature_columns is not None and len(feature_vector) != len(model.feature_columns):
        raise ValueError(
            f"ml_infer: feature_vector 길이({len(feature_vector)})가 학습된 모델의 "
            f"feature_columns 길이({len(model.feature_columns)})와 다릅니다."
        )
    contribs = model.feature_contribs(feature_vector)
    return {**model.score(feature_vector), "contribs": contribs}
