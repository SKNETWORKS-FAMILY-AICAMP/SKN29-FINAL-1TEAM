"""Draft Agent 계약 타입 — `api/draft.py`와 `agents/draft_agent.py`가 공유한다.

두 모듈이 서로를 import하는 순환 참조를 피하기 위해 공용 타입만 이 파일로 분리했다.
"""
from typing import Literal

CardType = Literal["PERSONAL", "TEAM", "SHARED", "POST_PAID", "PREPAID"]
Evidence = Literal["OK", "MISSING"]
#  **정본은 core의 `settlements.Category`다** — 운영 경로는 `core_client.get_categories()`로
#  런타임에 받아 쓴다(Draft Agent의 프롬프트·구조화 출력 enum 모두). 아래 Literal은
#  ① core 미기동 시 폴백 ② 요청 바디 타입(화면이 보낸 값의 1차 방어)로만 쓰인다.
#  `기타`는 "6개 중 어디에도 안 맞는다"는 **확정값**이고, 「아직 못 정했다」는 빈 문자열이다
#  (요청 필드가 Optional인 이유). 둘을 섞으면 미분류 건이 판정에서 확인된 것으로 취급된다.
Category = Literal["회식", "회의", "식대", "출장", "접대", "기타"]

# ── 가맹점 업종 어휘 (§7-1) ─────────────────────────────────────────────
# **정본은 core의 `domain/transactions/industry.py`다.** ai는 별도 컨테이너라 import할 수
# 없어 여기서 미러한다(`Category`와 같은 관례). 판정 사실(`merchant.merchant_type`)·룰
# DSL·금지업종 별표가 전부 이 라벨로 비교하므로 임의로 늘리거나 표기를 바꾸면 안 된다 —
# 어긋나면 캐시 적재 API(`MerchantCategoryUpsertView`)가 400으로 막는다.
IndustryLabel = Literal[
    "일반음식점", "카페", "주점/유흥", "노래연습장", "사행성업종",
    "숙박", "골프장", "레저", "마트/편의점", "면세점",
    "이·미용", "문구/사무용품", "주유/교통", "전자/가전", "기타",
]

INDUSTRY_CODES: dict[str, str] = {
    "일반음식점": "RESTAURANT",
    "카페": "CAFE",
    "주점/유흥": "BAR_ENTERTAINMENT",
    "노래연습장": "KARAOKE",
    "사행성업종": "GAMBLING",
    "숙박": "LODGING",
    "골프장": "GOLF",
    "레저": "LEISURE",
    "마트/편의점": "MART",
    "면세점": "DUTY_FREE",
    "이·미용": "PERSONAL_CARE",
    "문구/사무용품": "OFFICE_SUPPLIES",
    "주유/교통": "FUEL_TRANSPORT",
    "전자/가전": "ELECTRONICS",
    "기타": "OTHER",
}
