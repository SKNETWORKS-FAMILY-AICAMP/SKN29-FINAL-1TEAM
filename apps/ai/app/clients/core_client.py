"""Django 내부 read API 클라이언트 (기술명세서 §5.1).

관계형 데이터는 반드시 Django를 경유한다. LLM/Tool의 Postgres 직접 접근 금지.
"""
import httpx

from app.config import settings


def _get(path: str) -> dict:
    resp = httpx.get(f"{settings.core_base_url}{path}", timeout=10)
    resp.raise_for_status()
    return resp.json()


def health() -> dict:
    return _get("/api/health/")


def get_transaction(tx_id: int) -> dict:
    # TODO: Django 내부 조회 API(/api/internal/transactions/{id}/) 구현 후 연결
    return _get(f"/api/internal/transactions/{tx_id}/")


def get_policy(category: str) -> dict:
    """분류별 정책 한도 조회 (Django `PolicyTable` 별표, 내부 read API 경유)."""
    return _get(f"/api/internal/policies/{category}/")


def build_rule_context(settlement_id: int) -> dict:
    """판정용 EvalContext 조립 요청 (Django `context_builder`, 내부 read API 경유).

    별표 룩업·ORM 조회는 전부 Django에서 끝난다 — AI는 조립된 facts 스냅샷만 받는다.
    """
    return _get(f"/api/internal/rule-context/{settlement_id}/")


def get_settlement_summary(settlement_id: int) -> dict:
    """정산 요약(거래 ID·분류·가맹점·금액·목적) 조회 (Django `SettlementSummaryView`).

    Risk Review 2차 검증이 search_policy/search_cases 질의를 조립하고 get_tx_features를
    호출할 tx_id를 얻는 최소 진입점 — settlement_id만 있는 호출부가 관계형 조회 없이
    쓸 수 있게 한다(Postgres 직접 접근 금지 원칙).
    """
    return _get(f"/api/internal/settlement-summary/{settlement_id}/")


def get_tx_features(tx_id: int) -> dict:
    """이상탐지 입력용 원본 15개 피처 조회 (Django `transactions.features.build_tx_features`).

    카드별 과거 거래 집계(최근7일사용횟수 등)는 전부 Django에서 끝난다 — AI는 원-핫 인코딩 등
    "판단 없는 변환"만 `app.ml.features`로 수행한다.
    """
    return _get(f"/api/internal/tx-features/{tx_id}/")
