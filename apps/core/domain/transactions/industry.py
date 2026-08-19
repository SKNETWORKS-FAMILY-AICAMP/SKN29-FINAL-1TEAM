"""가맹점 업종 어휘 — 판정이 쓰는 **유일한 정본**(기술명세서 §7-1).

이 파일이 생기기 전까지 업종 어휘는 저장소 안에서 세 갈래로 갈려 있었다.

| 출처 | 표기 |
|---|---|
| `classify_merchant`(ai) | `주점/유흥` · `레저/골프` … (10종) |
| 룰 DSL(`seed_rules`) | `유흥업소` · `주점` · `노래연습장` · `골프장` … |
| 금지업종 별표(`tiger_tables`) | `유흥주점` · `단란주점` · `이용업` … |
| 시드·ERP 수집 실데이터 | `한식` · `분식` · `서점` · `종합소매` · `여객운송` … |

`Settlement.merchant_industry`는 `merchant.merchant_type` 사실로 그대로 엔진에 들어간다
(`policies/context_builder.py`). 어휘가 갈리면 `in [...]` 비교가 **조용히 안 걸리고**,
금지업종 별표는 `strict_keys=True`라 미등록 키가 `null` → `UNRESOLVED_FACT` → REVIEW 강등이
된다. 둘 다 화면에 아무 표시가 안 나므로 판정이 약해진 걸 알아채기 어렵다.

그래서 어휘를 여기 하나로 모으고, 룰·별표·시드·ERP·ai를 전부 이 표기로 옮겼다.

**어휘를 10종에서 늘린 이유**: 규정이 실제로 가르는 구분을 담아야 한다. 옛 10종은
`레저/골프` 하나로 골프장을 묶고 노래연습장·사행성업종·이미용업을 아예 담지 못했는데,
금지업종 별표(제9조②)와 주의업종 룰이 바로 그 구분으로 판정한다 — 어휘가 구분을 못 하면
룰을 아무리 잘 써도 판정할 수가 없다.

**모르면 `기타`로 밀지 않는다**: 매핑에 없는 값은 `("", "")`(미확정)으로 남긴다.
`기타`로 밀면 금지업종 별표에서 `"*" → False`(금지 아님)로 폴백해 **확인하지 않은 것을
안전하다고 단정**하게 된다. 미확정이면 `merchant.merchant_info_resolved=False`로 남아
사람이 보게 된다.

ai(FastAPI)는 별도 컨테이너라 import할 수 없어 `apps/ai/app/schemas.py`가 이 표를 **미러**한다
(`Category`와 같은 관례). 양쪽이 어긋나면 `MerchantCategoryUpsertView`가 400으로 막는다.
"""
from __future__ import annotations

import re

from django.db import models


class IndustryCode(models.TextChoices):
    """업종 코드(불변 데이터 계약) → 라벨(표기). 라벨이 곧 `merchant.merchant_type` 값이다."""

    RESTAURANT = "RESTAURANT", "일반음식점"
    CAFE = "CAFE", "카페"
    BAR_ENTERTAINMENT = "BAR_ENTERTAINMENT", "주점/유흥"
    KARAOKE = "KARAOKE", "노래연습장"
    GAMBLING = "GAMBLING", "사행성업종"
    LODGING = "LODGING", "숙박"
    GOLF = "GOLF", "골프장"
    LEISURE = "LEISURE", "레저"
    MART = "MART", "마트/편의점"
    DUTY_FREE = "DUTY_FREE", "면세점"
    PERSONAL_CARE = "PERSONAL_CARE", "이·미용"
    OFFICE_SUPPLIES = "OFFICE_SUPPLIES", "문구/사무용품"
    FUEL_TRANSPORT = "FUEL_TRANSPORT", "주유/교통"
    ELECTRONICS = "ELECTRONICS", "전자/가전"
    OTHER = "OTHER", "기타"


LABEL_BY_CODE: dict[str, str] = {c.value: c.label for c in IndustryCode}
CODE_BY_LABEL: dict[str, str] = {c.label: c.value for c in IndustryCode}

# 별칭 → 코드. 규정 원문 표기(유흥주점·이용업…), 옛 시드/ERP 표기(한식·서점…),
# 폐기된 ai 10종 표기(`레저/골프`)를 전부 정본으로 흡수한다.
#  ※ `레저/골프`는 **골프장**으로 접는다 — 주의업종 룰(T-50)이 골프장을 보고 있어서,
#    레저로 접으면 옛 값이 조용히 감시 대상에서 빠진다(느슨해지는 방향은 피한다).
ALIASES: dict[str, str] = {
    # 음식점
    "한식": IndustryCode.RESTAURANT, "일식": IndustryCode.RESTAURANT,
    "중식": IndustryCode.RESTAURANT, "양식": IndustryCode.RESTAURANT,
    "분식": IndustryCode.RESTAURANT, "치킨": IndustryCode.RESTAURANT,
    "음식점": IndustryCode.RESTAURANT, "식당": IndustryCode.RESTAURANT,
    "패스트푸드": IndustryCode.RESTAURANT, "고기": IndustryCode.RESTAURANT,
    # 카페
    "커피": IndustryCode.CAFE, "커피전문점": IndustryCode.CAFE,
    "제과": IndustryCode.CAFE, "베이커리": IndustryCode.CAFE, "디저트": IndustryCode.CAFE,
    # 주점·유흥 (규정 제9조② 표기 포함)
    "주점": IndustryCode.BAR_ENTERTAINMENT, "유흥업소": IndustryCode.BAR_ENTERTAINMENT,
    "유흥주점": IndustryCode.BAR_ENTERTAINMENT, "단란주점": IndustryCode.BAR_ENTERTAINMENT,
    "술집": IndustryCode.BAR_ENTERTAINMENT, "호프": IndustryCode.BAR_ENTERTAINMENT,
    "포차": IndustryCode.BAR_ENTERTAINMENT, "이자카야": IndustryCode.BAR_ENTERTAINMENT,
    "룸살롱": IndustryCode.BAR_ENTERTAINMENT, "클럽": IndustryCode.BAR_ENTERTAINMENT,
    # 노래연습장
    "노래방": IndustryCode.KARAOKE, "코인노래방": IndustryCode.KARAOKE,
    # 사행성
    "사행성": IndustryCode.GAMBLING, "사행성업종": IndustryCode.GAMBLING,
    "카지노": IndustryCode.GAMBLING, "경마장": IndustryCode.GAMBLING,
    "경륜장": IndustryCode.GAMBLING, "복권": IndustryCode.GAMBLING,
    # 숙박
    "호텔": IndustryCode.LODGING, "모텔": IndustryCode.LODGING,
    "리조트": IndustryCode.LODGING, "펜션": IndustryCode.LODGING, "게스트하우스": IndustryCode.LODGING,
    # 골프 / 레저
    "골프": IndustryCode.GOLF, "골프연습장": IndustryCode.GOLF,
    "스크린골프": IndustryCode.GOLF, "레저/골프": IndustryCode.GOLF,
    "스포츠": IndustryCode.LEISURE, "체육시설": IndustryCode.LEISURE,
    "테마파크": IndustryCode.LEISURE, "영화관": IndustryCode.LEISURE,
    # 유통
    "마트": IndustryCode.MART, "편의점": IndustryCode.MART,
    "슈퍼마켓": IndustryCode.MART, "종합소매": IndustryCode.MART, "대형마트": IndustryCode.MART,
    # 면세점
    "면세": IndustryCode.DUTY_FREE,
    # 이·미용 (규정 제9조② 표기)
    "이용업": IndustryCode.PERSONAL_CARE, "미용업": IndustryCode.PERSONAL_CARE,
    "미용실": IndustryCode.PERSONAL_CARE, "이발": IndustryCode.PERSONAL_CARE,
    "네일": IndustryCode.PERSONAL_CARE, "피부관리": IndustryCode.PERSONAL_CARE,
    # 사무용품
    "문구": IndustryCode.OFFICE_SUPPLIES, "서점": IndustryCode.OFFICE_SUPPLIES,
    "사무용품": IndustryCode.OFFICE_SUPPLIES, "인쇄": IndustryCode.OFFICE_SUPPLIES,
    # 주유·교통
    "주유": IndustryCode.FUEL_TRANSPORT, "주유소": IndustryCode.FUEL_TRANSPORT,
    "여객운송": IndustryCode.FUEL_TRANSPORT, "택시": IndustryCode.FUEL_TRANSPORT,
    "철도": IndustryCode.FUEL_TRANSPORT, "항공": IndustryCode.FUEL_TRANSPORT,
    "주차": IndustryCode.FUEL_TRANSPORT, "충전": IndustryCode.FUEL_TRANSPORT,
    # 전자·가전
    "전자제품": IndustryCode.ELECTRONICS, "가전": IndustryCode.ELECTRONICS,
    "컴퓨터": IndustryCode.ELECTRONICS,
}

# 부분일치 스캔 순서 — 긴 별칭이 먼저다("유흥주점"이 "주점"보다 먼저 걸려야 한다).
_ALIAS_BY_LENGTH: list[tuple[str, str]] = sorted(
    ALIASES.items(), key=lambda kv: -len(kv[0])
)

_WS = re.compile(r"\s+")


def _norm(value: str) -> str:
    return _WS.sub("", str(value or "")).strip()


def resolve(value: str | None) -> tuple[str, str]:
    """자유 표기(코드·라벨·별칭) → `(industry_code, industry_label)`. 못 찾으면 `("", "")`.

    정확일치(코드 → 라벨 → 별칭)를 먼저 보고, 그래도 없으면 별칭 부분일치로 한 번 더 본다
    ("강남한식당" 같은 옛 자유 표기를 흡수하기 위해서다). 부분일치는 긴 별칭부터 본다.
    """
    raw = _norm(value)
    if not raw:
        return ("", "")
    upper = raw.upper()
    if upper in LABEL_BY_CODE:
        return (upper, LABEL_BY_CODE[upper])
    if raw in CODE_BY_LABEL:
        return (CODE_BY_LABEL[raw], raw)
    code = ALIASES.get(raw)
    if code is None:
        for alias, alias_code in _ALIAS_BY_LENGTH:
            if alias in raw:
                code = alias_code
                break
    if code is None:
        return ("", "")
    return (str(code), LABEL_BY_CODE[str(code)])


def canonical_label(value: str | None) -> str:
    """판정에 올릴 라벨만 필요할 때. 미확정은 `""`(모름)."""
    return resolve(value)[1]
