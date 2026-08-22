"""타이거 주식회사 규정 별표 시드 데이터 — `_context/policy-domain.md` §2.

`TIGER-REG-2026-003` 계열 규정의 임계값 표를 `PolicyTable` 행으로 적재하기 위한 원본이다.
`seed_policy_tables` 관리 명령과 시연 EvalContext(`seed.py`)가 **이 모듈 하나만** 참조한다
— 임계값이 다시 여러 곳으로 흩어지지 않게 하는 것이 이 모듈의 존재 이유다.

⚠️ **값의 출처**: 여기 적힌 숫자는 기존 코드(`draft_agent.THRESHOLDS`·시드 그래프 DSL·시연
   EvalContext)에 흩어져 있던 값을 **그대로 모은 것**이다. 규정 별표 원문(`tiger_inc/`, RAG 소스)
   대조는 아직 하지 않았다. 운영 투입 전 `source_clause` 기준으로 원문 검수가 필요하다.

✅ **별표1(직책별 한도)은 원문 대조 완료**(2026-08-19, `tiger_inc/md/법인카드_사용규정.md` §별표1).
   축은 **`user.job_title`(직책)**이다 — 규정이 "한도는 보임 중인 **직책** 기준으로 적용되며,
   직급(사원~전무)과는 **무관**하다"고 못박는다. 이전 구현은 축을 `user.position`(직급)으로
   두고 payload에 직책(`본부장`)과 직급(`과장`·`대리`)을 섞어 놓았는데, 값도 규정과 달랐다.
   나머지 표(청탁금지·숙박·증빙·회식·기한)는 여전히 원문 미대조다.
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
    # ── 별표1 「직책별 법인카드 사용 한도」 — 원문 대조 완료 ──────────────────────
    #  와일드카드(`"*"`)는 **비직책자 값과 같게** 둔다. 직책을 모르는 사람에게 팀장 이상
    #  한도를 주면 규정보다 느슨해진다 — 모를 때는 가장 좁은 한도가 안전하다.
    {
        "key": "pre_approval_threshold_table",
        "title": "별표1. 직책별 건당 사전승인 기준",
        "key_axes": ["user.job_title"],
        "payload": {
            "*": 300_000,
            "비직책자(공용카드)": 300_000, "팀장": 500_000, "부서장": 600_000,
            "본부장": 800_000, "대표이사": 1_000_000,
        },
        "source_clause": f"{REG} 제10조② · 별표1",
    },
    {
        "key": "daily_limit_table",
        "title": "별표1. 직책별 1일 사용 한도",
        "key_axes": ["user.job_title"],
        "payload": {
            "*": 500_000,
            "비직책자(공용카드)": 500_000, "팀장": 1_000_000, "부서장": 1_500_000,
            "본부장": 2_500_000, "대표이사": 3_000_000,
        },
        "source_clause": f"{REG} 제10조① · 별표1",
    },
    {
        "key": "monthly_limit_table",
        "title": "별표1. 직책별 월 사용 한도",
        "key_axes": ["user.job_title"],
        "payload": {
            "*": 2_000_000,
            "비직책자(공용카드)": 2_000_000, "팀장": 4_000_000, "부서장": 5_000_000,
            "본부장": 8_000_000, "대표이사": 10_000_000,
        },
        "source_clause": f"{REG} 제10조① · 별표1",
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
        # 키는 **정본 업종 어휘 라벨**(`transactions.industry`)이다 — 규정 원문 표기
        #  (유흥주점·단란주점·이용업·미용업…)는 조립기가 정본으로 접어서 올리므로
        #  여기 원문 표기를 남겨두면 영영 안 걸린다.
        "payload": {
            "*": False,
            "주점/유흥": True, "노래연습장": True, "사행성업종": True, "이·미용": True,
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
        # ⚠️ 축을 뗐다(2026-08-22). 선언은 `category.scope`였는데 그건 EvalContext에 없는
        #    경로라 `resolve_path`가 늘 None을 돌려주고 `strict_keys=False` 폴백으로 **항상**
        #    `"*"`로 떨어졌다 — 값도 나오고 에러도 없어서 축이 죽은 걸 아무도 몰랐다.
        #    payload에 실제로 있는 값이 단일 한도 하나뿐이므로, 선언을 가진 데이터에 맞춘다.
        #    규정 원문(제14조①)에 조직단위(팀·본부·전사)별 값이 실재한다면 그때 `dining.org_unit`
        #    사실을 만들고 축을 되살린다 — **값이 생긴 다음에 축을 만드는** 순서가 맞다.
        "key": "dining_per_person_limit_table",
        "title": "회식 1인당 한도",
        "key_axes": [],
        "payload": _scalar(50_000),
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
    # 별표1의 **와일드카드(직책 미지정) 값** = 비직책자 한도. 시연 스냅샷과 조립기 결과가
    # 어긋나지 않게 여기 값도 별표1과 함께 움직인다(`test_resolved_values_match_demo_snapshot`).
    "preapproval_threshold": 300_000,
    "position_daily_limit": 500_000,
    "position_monthly_limit": 2_000_000,
    "kickback_limit": 30_000,
    "lodging_limit": 120_000,
    "evidence_threshold": 30_000,
    "dining_per_person_limit": 50_000,
    "settlement_deadline_days": 7,
}

# ctx.policy에 넣지 않고 조립기가 직접 쓰는 파라미터(DSL 비교 대상이 아닌 값).
HISTORY_WINDOW_TABLE = "history_window_table"
