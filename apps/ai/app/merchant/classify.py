"""가맹점 업종 구분 파이프라인 (기술명세서 §7-1).

캐스케이드: 정규화 → 자체 DB 캐시(Django, TTL 30일) → 카카오 지도 API(원시 업종) →
LLM 재분류(카카오 원시 카테고리 → 우리 서비스 업종 어휘) → 확정 시에만 캐시 upsert.

카카오의 `category_group_code`/`category_name`은 장소·마케팅 분류라 그대로 쓰지 않는다 —
예를 들어 일반 식당과 유흥주점이 둘 다 `FD6`(음식점)로 묶여 있어 비용분류 힌트로 쓰기엔
어휘가 안 맞는다. LLM이 가맹점명 + 카카오 원시 카테고리를 보고 `IndustryLabel`(우리 어휘)로
재분류한다. 웹검색 폴백은 두지 않는다 — 카카오에서도 못 찾으면 업종은 미확정으로 남긴다.

이 모듈은 MCP Tool(`app.mcp.tools.classify_merchant`)에서만 쓰인다 — Draft/Risk Agent
연동은 후속 과제(2026-08-18, 사용자 지시로 이번 범위에서 제외).

캐스케이드의 모든 단계(캐시 조회·카카오 조회·LLM 재분류·캐시 적재)는 개별적으로 실패해도
`classify()`가 예외를 던지지 않는다 — 캐시 조회 실패는 캐시 미스로 취급하고 계속 진행한다
(2026-08-19, core 장애 시 크래시 대신 미확정/저비용 저하로 수렴하도록 수정).
"""
from __future__ import annotations

import logging
import re
import time
from typing import Literal

import httpx
from openai import OpenAI
from pydantic import BaseModel

from app.clients import core_auth, core_client
from app.config import settings

logger = logging.getLogger(__name__)

UNRESOLVED = {"industry_code": "", "industry_label": "", "confidence": 0.0, "source": ""}

# ── 정규화 (§7-1 step 0) ────────────────────────────────────────────────
_CORP_PREFIX = re.compile(r"\(주\)|㈜")  # "주식회사" 표기 — 통짜로 제거(글자 "주"만 남기지 않는다)
_STRIP_CHARS = re.compile(r"[()（）※]")
_BRANCH_SUFFIX = re.compile(r"^(.+\S)\s+\S*(?:점|지점|본점|직영점)$")


def normalize(name: str) -> str:
    """지점명·특수문자·체인 접미 제거 → 조회 키 생성.

    "스타벅스 강남점" → "스타벅스"처럼 마지막 토큰이 "…점"류로 끝나면 그 토큰만 잘라낸다.
    한 단어짜리 이름(예: "던킨도너츠점")은 토큰이 하나뿐이라 대상이 아니다.
    """
    n = _CORP_PREFIX.sub("", name or "")
    n = _STRIP_CHARS.sub(" ", n)
    n = re.sub(r"\s+", " ", n).strip()
    m = _BRANCH_SUFFIX.match(n)
    if m:
        n = m.group(1)
    return n.strip()


# ── 카카오 지도 API (원시 업종) ─────────────────────────────────────────

def _kakao_search(query: str) -> dict | None:
    """카카오 로컬 키워드검색. 키가 없으면 호출 자체를 생략한다."""
    if not settings.kakao_rest_api_key:
        return None
    resp = httpx.get(
        "https://dapi.kakao.com/v2/local/search/keyword.json",
        params={"query": query, "size": 1},
        headers={"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"},
        timeout=10,
    )
    resp.raise_for_status()
    docs = resp.json().get("documents") or []
    return docs[0] if docs else None


# ── LLM 재분류 — 카카오 원시 카테고리 → 우리 서비스 업종 어휘 ──────────

IndustryLabel = Literal[
    "일반음식점", "카페", "주점/유흥", "숙박", "레저/골프",
    "마트/편의점", "문구/사무용품", "주유/교통", "전자/가전", "기타",
]

_INDUSTRY_CODES: dict[str, str] = {
    "일반음식점": "RESTAURANT",
    "카페": "CAFE",
    "주점/유흥": "BAR_ENTERTAINMENT",
    "숙박": "LODGING",
    "레저/골프": "LEISURE",
    "마트/편의점": "MART",
    "문구/사무용품": "OFFICE_SUPPLIES",
    "주유/교통": "FUEL_TRANSPORT",
    "전자/가전": "ELECTRONICS",
    "기타": "OTHER",
}

MODEL = "gpt-4o-mini"

_SYSTEM_PROMPT = """당신은 법인카드 정산 시스템의 가맹점 업종 분류 보조입니다.
카카오 지도 검색 결과(가맹점명, 카테고리 정보)를 보고 아래 10개 업종 중 하나로 분류하세요:
일반음식점, 카페, 주점/유흥, 숙박, 레저/골프, 마트/편의점, 문구/사무용품, 주유/교통, 전자/가전, 기타

분류 기준:
1. 술집·호프·포차·노래방 등 유흥성 업소는 "일반음식점"이 아니라 "주점/유흥"으로 분류하세요
   (비용 리스크 판단에 쓰이는 구분이라 정확도가 중요합니다).
2. 카카오 카테고리가 애매하거나 여러 업종에 걸치면 가맹점명도 함께 참고하세요.
3. 어느 업종에도 뚜렷이 맞지 않으면 "기타"로 분류하고 confidence를 낮게 주세요.
4. 이 분류는 세무·회계 판단의 근거가 아니라 비용분류 제안을 위한 보조 힌트입니다."""

_USER_PROMPT_TEMPLATE = """가맹점명: {merchant}
카카오 카테고리(상세): {category_name}
카카오 카테고리(대분류): {category_group_name}"""

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


class _LLMIndustryOutput(BaseModel):
    industry_label: IndustryLabel
    confidence: float


def _llm_classify(merchant: str, category_name: str, category_group_name: str) -> _LLMIndustryOutput:
    """카카오 원시 카테고리를 우리 업종 어휘로 재분류. 실패하면 예외를 그대로 올린다 —
    호출부(`classify`)가 미확정으로 폴백한다(원시 카카오 라벨을 대신 쓰지 않는다)."""
    user_prompt = _USER_PROMPT_TEMPLATE.format(
        merchant=merchant, category_name=category_name, category_group_name=category_group_name,
    )
    started = time.perf_counter()
    resp = _get_client().beta.chat.completions.parse(
        model=MODEL,
        temperature=0.1,
        timeout=15,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format=_LLMIndustryOutput,
    )
    parsed = resp.choices[0].message.parsed
    if parsed is None:
        raise ValueError("LLM이 구조화된 응답을 반환하지 않았습니다(모델 거부 등)")
    logger.info(
        "merchant classify LLM merchant=%r -> %s (%.0fms)",
        merchant, parsed.industry_label, (time.perf_counter() - started) * 1000,
    )
    return parsed


# ── 캐스케이드 본체 ──────────────────────────────────────────────────

def classify(merchant: str, place_hint: str | None = None) -> dict:
    """캐시 → 카카오 → LLM 재분류 캐스케이드(§7-1). 미확정이면 빈 필드로 반환(예외 아님)."""
    name = normalize(merchant)
    if not name:
        return dict(UNRESOLVED)

    try:
        cached = core_client.get_merchant_category(name)
    except Exception as exc:  # noqa: BLE001  # core 장애·타임아웃 — 캐시 미스로 취급하고 계속 진행
        logger.warning("가맹점 업종 캐시 조회 실패(merchant=%r): %s — 캐시 미스로 처리", merchant, exc)
        cached = {"hit": False}

    if cached.get("hit"):
        return {
            "industry_code": cached.get("industry_code", ""),
            "industry_label": cached.get("industry_label", ""),
            "confidence": cached.get("confidence", 0.0),
            "source": "CACHE",
        }

    query = f"{name} {place_hint}".strip() if place_hint else name
    try:
        doc = _kakao_search(query)
    except Exception as exc:  # noqa: BLE001  # 네트워크 오류·타임아웃·401 등
        logger.warning("카카오 지도 조회 실패(merchant=%r): %s", merchant, exc)
        doc = None

    if not doc:
        return dict(UNRESOLVED)

    try:
        llm_out = _llm_classify(merchant, doc.get("category_name", ""), doc.get("category_group_name", ""))
    except Exception as exc:  # noqa: BLE001  # OpenAI 키 없음·타임아웃·거부 등
        logger.warning("LLM 업종 재분류 실패(merchant=%r): %s — 미확정 처리", merchant, exc)
        return dict(UNRESOLVED)

    industry_label = llm_out.industry_label
    industry_code = _INDUSTRY_CODES[industry_label]
    confidence = llm_out.confidence

    try:
        core_auth.request(
            "POST", "/api/internal/merchant-category/",
            json={
                "normalized_name": name,
                "place_id": doc.get("id", ""),
                "industry_code": industry_code,
                "industry_label": industry_label,
                "source": "KAKAO",
                "confidence": confidence,
                "raw": doc,
            },
            timeout=15.0,
        )
    except Exception as exc:  # noqa: BLE001  # 캐시 적재 실패해도 이번 조회 결과는 그대로 돌려준다
        logger.error("가맹점 업종 캐시 적재 실패(merchant=%r): %s", merchant, exc)

    return {
        "industry_code": industry_code,
        "industry_label": industry_label,
        "confidence": confidence,
        "source": "KAKAO",
    }
