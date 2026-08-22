"""Django 내부 read API 클라이언트 (기술명세서 §5.1).

관계형 데이터는 반드시 Django를 경유한다. LLM/Tool의 Postgres 직접 접근 금지.
"""
import logging
from urllib.parse import quote

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _get(path: str, timeout: float = 10) -> dict:
    resp = httpx.get(f"{settings.core_base_url}{path}", timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def health() -> dict:
    return _get("/api/health/")


def get_transaction(tx_id: int) -> dict:
    # TODO: Django 내부 조회 API(/api/internal/transactions/{id}/) 구현 후 연결
    return _get(f"/api/internal/transactions/{tx_id}/")


_categories_cache: list[str] | None = None


def get_categories(*, refresh: bool = False) -> list[str]:
    """비용분류 어휘 정본(`settlements.Category`)을 Django에서 받아 온다.

    **여기서 목록을 들고 있지 않는다.** ai가 자체 상수를 두면 core가 분류를 늘렸을 때
    Draft Agent 프롬프트·구조화 출력 enum만 옛 목록으로 남아, LLM이 새 분류를 아예
    고를 수 없게 된다(`rule_agent_v0/django_client.get_action_schema`가 decision/severity
    카탈로그를 같은 이유로 core에서 받아 오는 것과 같은 관례).

    프로세스 수명 동안 캐시한다 — 어휘는 배포 단위로만 바뀐다. 조회에 실패하면 정적
    미러(`app.schemas.Category`)로 떨어진다: 초안 작성 전체가 core 가용성에 묶이는 것보다
    한 세대 낡은 목록으로라도 도는 편이 낫다(값이 사라지는 변경은 없으므로 안전한 방향).
    """
    global _categories_cache
    if _categories_cache is not None and not refresh:
        return _categories_cache

    try:
        data = _get("/api/meta/categories/", timeout=5)
        values = [str(row["value"]) for row in data.get("categories", []) if row.get("value")]
    except Exception:  # noqa: BLE001  # core 미기동·타임아웃·형식 변경 전부
        from typing import get_args

        from app.schemas import Category as CategoryLiteral

        logger.warning("비용분류 어휘 조회 실패 — 정적 미러(app.schemas.Category)로 폴백")
        values = list(get_args(CategoryLiteral))

    if values:
        _categories_cache = values
    return values


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


def get_draft_context(settlement_id: int, timeout: float = 15) -> dict:
    """Draft Agent 입력 한 묶음 (Django `SettlementDraftContextView`).

    기본 내역(ERP 수집·영수증 비전·카드 원장)·업종·첨부 추출 사실·EvalContext·**엔진 판정
    미리보기**·보완요청 맥락이 한 번에 온다. 초안이 「지어낼 수 없어야 하는 것」은 전부
    여기서 오고, 모델에게는 분류·목적·설명만 남는다.

    실패는 감추지 않고 올린다 — 사실 없이 초안을 쓰면 그게 정확히 이 구조가 없앤 문제다
    (모델이 폼 값만 보고 그럴듯한 문장을 만들던 상태로 되돌아간다).
    """
    return _get(f"/api/internal/settlement-draft-context/{settlement_id}/", timeout=timeout)


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


def get_merchant_category(normalized_name: str, timeout: float = 10) -> dict:
    """가맹점 업종 캐시 조회 (Django `MerchantCategoryLookupView`, §7-1).

    TTL(30일) 판정은 Django 쪽에서 끝낸다 — 여기선 `hit` 여부만 본다.
    """
    return _get(f"/api/internal/merchant-category/{quote(normalized_name, safe='')}/", timeout=timeout)
