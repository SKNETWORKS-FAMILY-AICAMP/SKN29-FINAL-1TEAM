"""룰 그래프 scope(계정과목별) ↔ 정산 비용분류(Category) 정합.

룰 도메인의 계정과목별 그래프는 settlements.Category를 scope의 SoT로 쓴다(기술 §4.2·FR-RA-10).
규정 문서(룰 명세서)의 과목명(기업업무추진비·회식 등)은 아래 매핑으로 Category 값에 정규화한다.
정식 회계 계정과목 테이블은 두지 않는다(세무 판단은 RAG/세법에 위임 — FR-DA-03c). GLOBAL은
카테고리 무관 필수 게이트라 매핑 대상이 아니다. (요구사항 Open #9 정합)
"""
from domain.settlements.models import Category

GLOBAL = "GLOBAL"

# 룰 명세서 과목명/별칭 → 정산 비용분류(Category) 값.
#  회식은 별도 Category가 없어 식대(MEAL) scope 그래프에 함께 편성한다(회식 RULE은 그래프 내 노드로 구분).
RULE_SUBJECT_TO_CATEGORY = {
    "기업업무추진비": Category.ENTERTAIN,
    "접대": Category.ENTERTAIN,
    "회식": Category.MEAL,
    "식대": Category.MEAL,
    "출장": Category.TRIP,
    "회의": Category.MEETING,
    "비품": Category.SUPPLIES,
    "업무활성": Category.OPERATION,
}


def normalize_scope(subject: str) -> str:
    """룰 그래프 scope 문자열 정규화 — GLOBAL은 그대로, 과목명은 Category 값으로.

    매핑에 없는 값은 원문 유지(향후 분류 확장 여지). 엔진 구현 시 그래프 선택의 단일 기준점.
    """
    if not subject or subject.upper() == GLOBAL:
        return GLOBAL
    cat = RULE_SUBJECT_TO_CATEGORY.get(subject)
    return cat.value if cat else subject
