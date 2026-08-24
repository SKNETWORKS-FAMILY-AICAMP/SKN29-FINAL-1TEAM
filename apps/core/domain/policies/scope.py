"""룰 그래프 scope(계정과목별) ↔ 정산 비용분류(Category) 정합.

룰 도메인의 계정과목별 그래프는 settlements.Category를 scope의 SoT로 쓴다(기술 §4.2·FR-RA-10).
규정 문서(룰 명세서)의 과목명(기업업무추진비·회식 등)은 아래 매핑으로 Category 값에 정규화한다.
정식 회계 계정과목 테이블은 두지 않는다(세무 판단은 RAG/세법에 위임 — FR-DA-03c). GLOBAL은
카테고리 무관 필수 게이트라 매핑 대상이 아니다. (요구사항 Open #9 정합)
"""
from domain.settlements.models import Category

GLOBAL = "GLOBAL"

# 룰 명세서 과목명/별칭 → 정산 비용분류(Category) 값.
#  [2026-08-14 정정] 회식은 더 이상 식대(MEAL)에 얹혀가는 별칭이 아니다 — Category.GATHERING("회식")
#  으로 독립했다. "업무활성"은 폐지(Category.GATHERING으로 슬롯 대체, 값은 무관한 개념이라
#  재사용 캐치올은 SUPPLIES로 흡수 — draft_agent.py 참조). 매핑에 없는 값은 normalize_scope가
#  원문 그대로 통과시키므로("회식"→"회식") 자기 자신을 가리키는 항목은 여기 안 둔다.
RULE_SUBJECT_TO_CATEGORY = {
    "기업업무추진비": Category.ENTERTAIN,
    "접대": Category.ENTERTAIN,
    "식대": Category.MEAL,
    "출장": Category.TRIP,
    "회의": Category.MEETING,
    #  2026-08-24: "비품"은 Category에서 폐기됐다(과목 5종+기타로 단순화). 규정 문서에
    #  「비품」 과목이 나와도 그 자리를 대신할 정본 값이 없으므로 **매핑하지 않는다** —
    #  `normalize_scope`가 원문을 그대로 통과시키고, ACTIVE 전환 시 CHECK 제약이 막는다.
    #  임의로 `기타`에 붙이면 "비품 규정"으로 만든 그래프가 조용히 기타 과목을 판정한다.
}


def normalize_scope(subject: str) -> str:
    """룰 그래프 scope 문자열 정규화 — GLOBAL은 그대로, 과목명은 Category 값으로.

    매핑에 없는 값은 원문 유지(향후 분류 확장 여지). 엔진 구현 시 그래프 선택의 단일 기준점.
    """
    if not subject or subject.upper() == GLOBAL:
        return GLOBAL
    cat = RULE_SUBJECT_TO_CATEGORY.get(subject)
    return cat.value if cat else subject
