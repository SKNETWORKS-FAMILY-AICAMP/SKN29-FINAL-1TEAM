"""FastMCP 도구 구현 (기술명세서 §5, §5.1).

접근 경로 원칙:
- 관계형 데이터(거래·규정·정산·카드) → Django 내부 read API 경유
- 벡터 데이터(규정/사례 임베딩)     → Chroma 직접
- LLM/Tool은 Postgres에 직접 SQL 금지
스캐폴드: 대부분 stub 반환. TODO 표기.
"""
from __future__ import annotations

from app.ml.registry import get_active_model


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
