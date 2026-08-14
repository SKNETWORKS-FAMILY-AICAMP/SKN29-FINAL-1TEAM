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


def judge_settlement(settlement_id: int) -> dict:
    """RPA 1차판정 실행 요청 (Django `settlements.services.judge`).

    **판정 로직을 이쪽에 복제하지 않는다.** 판정은 그래프 선택·엔진 순회·`rule_hits` 기록·
    상태 전이가 한 트랜잭션으로 묶여야 하고, 그 셋 다 Postgres를 쓴다 — FastAPI는
    관계형 데이터에 직접 접근하지 않는다(§5.1). LLM도 개입하지 않으므로(FR-RA-06)
    AI가 중간에서 할 일 자체가 없다. 이 함수는 호출 경로를 유지하기 위한 위임이다.
    """
    resp = httpx.post(
        f"{settings.core_base_url}/api/settlements/{settlement_id}/judge/", timeout=30
    )
    resp.raise_for_status()
    return resp.json()
