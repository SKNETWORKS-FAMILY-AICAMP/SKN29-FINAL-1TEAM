"""타이거 주식회사 규정 별표 시드 데이터 — `_context/policy-domain.md` §2.

`TIGER-REG-2026-003` 계열 규정의 임계값 표를 `PolicyTable` 행으로 적재하기 위한 원본이다.
`seed_policy_tables` 관리 명령과 시연 EvalContext(`seed.py`)가 **이 모듈 하나만** 참조한다
— 임계값이 다시 여러 곳으로 흩어지지 않게 하는 것이 이 모듈의 존재 이유다.

⚠️ **값의 출처**: 여기 적힌 숫자는 기존 코드(`draft_agent.THRESHOLDS`·시드 그래프 DSL·시연
   EvalContext)에 흩어져 있던 값을 **그대로 모은 것**이다. 규정 별표 원문(`tiger_inc/`, RAG 소스)
   대조는 아직 하지 않았다. 운영 투입 전 `source_clause` 기준으로 원문 검수가 필요하다.

⚠️ **`user.position` 축**: 현재 SoR(`accounts.User`)에 직책 필드가 없어 조립기가 키를 만들 수
   없다. 그래서 직책 축 표는 `"*"`(와일드카드) 항목만 두고, 직책 필드가 생기면 항목을 추가하는
   방식으로 확장한다. 와일드카드가 있으므로 지금도 해소는 성공한다(미해소 플래그 안 뜸).
"""
from __future__ import annotations

from datetime import date

REG = "TIGER-REG-2026-003"
EFFECTIVE_FROM = date(2026, 1, 1)


def _scalar(value):
    """축이 없는 전역 임계값의 payload 형태."""
    return {"value": value}


# key → (title, key_axes, payload, source_clause)
TABLES: list[dict] = [
    {
        "key": "pre_approval_threshold_table",
        "title": "별표1. 직책별 사전승인 기준액",
        "key_axes": ["user.position"],
        "payload": {"*": 500_000},
        "source_clause": f"{REG} 제12조① · 별표1",
    },
    {
        "key": "daily_limit_table",
        "title": "별표1. 직책별 1일 사용 한도",
        "key_axes": ["user.position"],
        "payload": {"*": 600_000, "본부장": 600_000, "과장": 300_000, "대리": 400_000},
        "source_clause": f"{REG} 별표1",
    },
    {
        "key": "monthly_limit_table",
        "title": "별표1. 직책별 월 사용 한도",
        "key_axes": ["user.position"],
        "payload": {"*": 3_000_000, "본부장": 3_000_000, "대리": 2_000_000},
        "source_clause": f"{REG} 별표1",
    },
    {
        "key": "kickback_limit_table",
        "title": "청탁금지법 유형별 1인당 한도",
        "key_axes": ["category.item_type"],
        # 축 = 선물 유형(구 policy.gift_type). 정책값이 아니라 룩업 키라서 category로 옮겼다.
        "payload": {"*": 30_000, "음식물": 30_000},
        "source_clause": "청탁금지법 제8조 · 기업업무추진비 규정 별표1",
    },
    {
        "key": "lodging_limit_table",
        "title": "별표2. 출장구분·지역등급별 1박 숙박비 한도",
        "key_axes": ["trip.trip_type", "trip.region_grade"],
        "payload": {"*": {"*": 120_000}, "국내": {"*": 120_000, "B": 120_000}},
        "source_clause": f"{REG} 제17조② · 별표2",
    },
    {
        # 금지업종 목록 — merchant.forbidden 불린으로 선해소한다.
        # DSL의 `in`은 리터럴 리스트만 받으므로 목록을 룰에 박으면 규정 개정을 못 따라간다.
        "key": "forbidden_merchant_table",
        "title": "제9조② 사용 금지 업종",
        "key_axes": ["merchant.merchant_type"],
        # 업종을 모르면 "금지 아님"으로 단정하지 않는다 — null로 남겨 사람이 보게 한다.
        "strict_keys": True,
        "payload": {
            "*": False,
            "유흥주점": True, "단란주점": True, "노래연습장": True, "사행성업종": True,
            "카지노": True, "경마장": True, "이용업": True, "미용업": True,
        },
        "source_clause": f"{REG} 제9조②",
    },
    # ── 분류(Category) 축 표 — 구 `Policy` 모델이 담던 "분류별 한도·필요증빙"의 이전 대상.
    #    Draft Agent(`PolicyLookupView` → `get_policy`)가 이 두 표를 읽는다.
    {
        "key": "evidence_threshold_table",
        "title": "분류별 적격증빙 필수 기준액",
        "key_axes": ["category.value"],
        "payload": {"*": 30_000},
        "source_clause": f"{REG} 제11조②",
    },
    {
        "key": "required_evidence_table",
        "title": "분류별 필요증빙",
        "key_axes": ["category.value"],
        "payload": {"*": ["영수증"]},          # 리프가 리스트인 유일한 표
        "source_clause": f"{REG} 제11조",
    },
    {
        "key": "dining_per_person_limit_table",
        "title": "회식 조직단위별 1인당 한도",
        "key_axes": ["category.scope"],
        "payload": {"*": 50_000},
        "source_clause": f"{REG} 제14조①",
    },
    {
        "key": "settlement_deadline_table",
        "title": "분류별 정산 제출 기한(영업일)",
        "key_axes": ["category.value"],
        "payload": {"*": 7},
        "source_clause": f"{REG} 제12조",
    },
    # ── 축 없는 전역 임계값
    {
        # ctx.policy에는 넣지 않는다(DSL 비교 대상이 아님). 조립기가 history 집계에 쓴다.
        "key": "history_window_table",
        "title": "이력 집계 윈도우(개월)",
        "key_axes": [],
        "payload": _scalar(3),
        "source_clause": f"{REG} 제8조 운영기준",
    },
]

# ── 시연·테스트용 기본 정책값 스냅샷.
#    별표의 와일드카드(`*`) 값을 그대로 펼친 것이라 조립기 결과와 어긋나지 않는다.
def upsert_all(effective_date=EFFECTIVE_FROM) -> int:
    """별표를 DB에 적재한다(시드·재시드 공용). 같은 (key, effective_date)는 갱신한다.

    운영 개정은 이 함수가 아니라 **새 effective_date 행 추가**로 해야 한다 — 여기서 값을
    덮어쓰면 과거 판정 재현이 깨진다. 이 함수는 초기 적재·개발 재시드 전용이다.
    """
    from .models import PolicyTable

    for spec in TABLES:
        PolicyTable.objects.update_or_create(
            key=spec["key"], effective_date=effective_date,
            defaults={
                "title": spec["title"],
                "key_axes": spec["key_axes"],
                "payload": spec["payload"],
                "strict_keys": spec.get("strict_keys", False),
                "source_clause": spec["source_clause"],
            },
        )
    return len(TABLES)


DEMO_POLICY: dict[str, object] = {
    "preapproval_threshold": 500_000,
    "position_daily_limit": 600_000,
    "position_monthly_limit": 3_000_000,
    "kickback_limit": 30_000,
    "lodging_limit": 120_000,
    "evidence_threshold": 30_000,
    "dining_per_person_limit": 50_000,
    "settlement_deadline_days": 7,
}

# ctx.policy에 넣지 않고 조립기가 직접 쓰는 파라미터(DSL 비교 대상이 아닌 값).
HISTORY_WINDOW_TABLE = "history_window_table"
