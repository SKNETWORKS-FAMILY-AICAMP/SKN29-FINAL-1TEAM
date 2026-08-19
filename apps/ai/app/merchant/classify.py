"""가맹점 업종 구분 파이프라인 (기술명세서 §7-1).

캐스케이드: 정규화 → 자체 DB 캐시(Django, TTL 30일) → 카카오 지도 API(원시 업종) →
LLM 재분류(카카오 원시 카테고리 → 우리 서비스 업종 어휘) → 확정 시에만 캐시 upsert.

카카오의 `category_group_code`/`category_name`은 장소·마케팅 분류라 그대로 쓰지 않는다 —
예를 들어 일반 식당과 유흥주점이 둘 다 `FD6`(음식점)로 묶여 있어 비용분류 힌트로 쓰기엔
어휘가 안 맞는다. LLM이 가맹점명 + 카카오 원시 카테고리를 보고 `IndustryLabel`(우리 어휘)로
재분류한다. 웹검색 폴백은 두지 않는다 — 카카오에서도 못 찾으면 업종은 미확정으로 남긴다.

호출부는 MCP Tool(`app.mcp.tools.classify_merchant`)과 **Draft Agent**(`agents/draft_agent.py`)다.
Draft는 사용자가 화면 앞에서 기다리는 경로라 각 단계 타임아웃을 짧게 잡는다(아래 `*_TIMEOUT`) —
업종은 보조 힌트일 뿐이라 못 채워도 초안 작성은 계속돼야 한다.
"""
from __future__ import annotations

import logging
import re
import time

import httpx
from openai import OpenAI
from pydantic import BaseModel

from app.clients import core_auth, core_client
from app.config import settings
from app.schemas import INDUSTRY_CODES, IndustryLabel

logger = logging.getLogger(__name__)

UNRESOLVED = {"industry_code": "", "industry_label": "", "confidence": 0.0, "source": ""}

# 단계별 타임아웃(초). Draft 초안 작성 안에서 동기로 도는 경로라 **총 대기 시간이 곧 화면 대기**다.
# 캐시 히트면 이 중 첫 줄만 쓴다(수십 ms). 미스일 때의 최악 합이 Django `/agent/draft`
# 타임아웃(40s) 안에 draft 자신의 LLM 호출(15s)과 함께 들어가야 한다.
CACHE_TIMEOUT = 3.0
KAKAO_TIMEOUT = 4.0
LLM_TIMEOUT = 8.0
UPSERT_TIMEOUT = 4.0

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

_warned_no_key = False


def _kakao_search(query: str) -> dict | None:
    """카카오 로컬 키워드검색. 키가 없으면 호출 자체를 생략한다.

    **키 부재는 한 번 경고로 남긴다** — 조용히 건너뛰면 캐시 미스가 전부 "업종 미확정"으로
    보이는데, 그게 키가 없어서인지 카카오가 못 찾아서인지 로그에서 구분되지 않는다.
    """
    global _warned_no_key
    if not settings.kakao_rest_api_key:
        if not _warned_no_key:
            logger.warning(
                "KAKAO_REST_API_KEY가 비어 있어 가맹점 업종 조회를 건너뜁니다 "
                "— 캐시에 없는 가맹점은 업종 미확정으로 남습니다(.env 확인)."
            )
            _warned_no_key = True
        return None
    resp = httpx.get(
        "https://dapi.kakao.com/v2/local/search/keyword.json",
        params={"query": query, "size": 1},
        headers={"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"},
        timeout=KAKAO_TIMEOUT,
    )
    resp.raise_for_status()
    docs = resp.json().get("documents") or []
    return docs[0] if docs else None


# ── LLM 재분류 — 카카오 원시 카테고리 → 우리 서비스 업종 어휘 ──────────

# 업종 어휘·코드는 정본 미러(`app/schemas.py`)를 쓴다 — 여기서 따로 들고 있으면
# core(`domain/transactions/industry.py`)와 갈라진다(이미 한 번 갈라져 룰이 안 걸렸다).

MODEL = "gpt-4o-mini"

# 어휘를 프롬프트에 손으로 적지 않고 정본에서 만든다 — 표가 늘면 프롬프트도 같이 는다.
_INDUSTRY_LIST = ", ".join(INDUSTRY_CODES)

_SYSTEM_PROMPT = f"""당신은 법인카드 정산 시스템의 가맹점 업종 분류 보조입니다.
카카오 지도 검색 결과(가맹점명, 카테고리 정보)를 보고 아래 업종 중 **하나로만** 분류하세요:
{_INDUSTRY_LIST}

분류 기준:
1. 술집·호프·포차·이자카야·룸살롱 등 유흥성 업소는 "일반음식점"이 아니라 "주점/유흥"입니다
   (회사 규정이 금지 업종으로 정한 구분이라 정확도가 중요합니다).
2. 노래연습장(노래방)은 "주점/유흥"이 아니라 "노래연습장"으로 따로 분류하세요.
   카지노·경마장·복권 등은 "사행성업종", 미용실·이발소·네일숍 등은 "이·미용"입니다.
   — 이 셋은 규정이 각각 다르게 다루므로 묶지 마세요.
3. 골프장·골프연습장·스크린골프는 "골프장", 그 밖의 여가시설(체육시설·테마파크·영화관)은 "레저"입니다.
4. 카카오 카테고리가 애매하거나 여러 업종에 걸치면 가맹점명도 함께 참고하세요.
5. 어느 업종에도 뚜렷이 맞지 않으면 "기타"로 분류하고 confidence를 낮게 주세요.
6. 이 분류는 세무·회계 판단의 근거가 아니라 비용분류 제안을 위한 보조 힌트입니다."""

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
        timeout=LLM_TIMEOUT,
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

    # 캐시 조회 실패(=Django 미기동·타임아웃)를 흡수한다. 카카오·LLM 실패는 잡으면서
    # 여기만 안 잡혀 있어서, core가 죽으면 "미확정 반환" 계약을 깨고 예외가 튀어나갔다.
    try:
        cached = core_client.get_merchant_category(name, timeout=CACHE_TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        logger.warning("가맹점 업종 캐시 조회 실패(merchant=%r): %s", merchant, exc)
        cached = {}
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
    industry_code = INDUSTRY_CODES[industry_label]
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
            timeout=UPSERT_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001  # 캐시 적재 실패해도 이번 조회 결과는 그대로 돌려준다
        logger.error("가맹점 업종 캐시 적재 실패(merchant=%r): %s", merchant, exc)

    return {
        "industry_code": industry_code,
        "industry_label": industry_label,
        "confidence": confidence,
        "source": "KAKAO",
    }
