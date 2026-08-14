"""FastMCP 도구 구현 (기술명세서 §5, §5.1).

접근 경로 원칙:
- 관계형 데이터(거래·규정·정산·카드) → Django 내부 read API 경유
- 벡터 데이터(규정/사례 임베딩)     → Chroma 직접
- LLM/Tool은 Postgres에 직접 SQL 금지
스캐폴드: 대부분 stub 반환. TODO 표기.
"""
from __future__ import annotations

import logging

from app.clients import core_client
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


def search_policy(query: str, top_k: int = 6, include_law: bool = False) -> dict:
    """규정 청크 RAG 검색 (Chroma 직접). Rule/Risk 공용 tool.

    구현 실체는 `agents/rule_agent_v0/search.py` — 그쪽이 팀 RAG 정본
    (`rag/embedding/store.search`)을 부모 필터·부모 확장·컬렉션 라우팅까지 그대로 쓴다.
    Risk Review Agent도 **이 tool을 거쳐** 같은 검색 경로·로깅을 공유해야 한다(§5).

    조회 실패는 감추지 않고 올린다 — 빈 결과와 장애를 구분해야 "규정이 아직 안 실렸다"와
    "Chroma가 죽었다"를 화면에서 가려낼 수 있다.
    """
    from app.agents.rule_agent_v0.search import search_policy as _search

    chunks = _search(query, top_k=top_k, include_law=include_law)
    logger.info("search_policy q=%r top_k=%d hits=%d", query, top_k, len(chunks))
    return {"query": query, "chunks": chunks}


def search_cases(query: str) -> dict:
    """유사 과거 승인/반려 사례 검색 (Chroma 직접). Risk."""
    return {"query": query, "similar_cases": []}


def fetch_historical_tx(period: str, filters: dict | None = None) -> dict:
    """과거 거래 로드 (Django 경유). Rule 검증(시뮬레이션)."""
    return {"period": period, "tx": []}


def build_rule_context(settlement_id: int) -> dict:
    """판정용 EvalContext(facts 스냅샷) 조립 (Django 경유, `RuleContextView`). Rule(적용).

    별표 룩업·ORM 조회는 Django의 조립기가 전부 끝낸다. `unresolved_policy_fields`가
    비어 있지 않으면 그 필드를 참조하는 룰은 판정을 신뢰할 수 없다(엔진이 REVIEW로 강등).
    """
    return core_client.build_rule_context(settlement_id)


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
