"""직책·직급 기준 코드 (조직 마스터 데이터) — 타이거 규정 원문 대조 완료.

## 두 축은 하는 일이 다르다 (「직급체계」 §1 · 「법인카드 사용 규정」 별표1)

  · **직책(JobTitle)** = 보임된 자리. **결재권·카드한도의 유일한 축**이다.
      규정 원문: "결재 권한 및 법인카드 사용한도는 **직책** 기준으로 부여한다(직급 기준이 아니다)"
      별표1 각주: "한도는 보임 중인 **직책** 기준으로 적용되며, 직급(사원~전무)과는 무관하다"
  · **직급(Position)** = 연차·근속 호칭. **급여·승진 등 처우** 기준이며 판정에 쓰지 않는다.

그래서 `EvalContext`에 올라가는 건 **직책뿐**이다. 직급을 판정 축으로 쓰면 규정과 정반대가
된다 — 같은 '이사'라도 부서장 겸직이냐 본부장 대행이냐에 따라 한도가 달라지기 때문에
(별표1 각주), 직급으로는 한도를 결정할 수 **없다**.

## 왜 문서(RAG) 선해소가 아니라 DB인가

별표는 "직책별 한도"라는 *표*이고, 어떤 사람이 무슨 직책인지는 *그 사람에 붙은 사실*이다.
후자를 문서에서 뽑으면 셋이 깨진다 —
  ① 재현성(FR-RA-08): 같은 정산이 재색인 뒤 다른 판정을 낸다.
  ② 엔티티 매칭: 조직도는 이름을 싣는데 "김민수 → user#3"은 동명이인·퇴사자에서 조용히 틀린다.
  ③ 갱신 주기: 규정이 "직책 변경 시 **발령일**부터 적용"이라 발령 사실이 원천이지 문서가 아니다.

⚠️ **`name`이 별표의 룩업 키다.** `policies/tiger_tables.py`의 payload가 이 문자열로 직접
인덱싱되므로 한 글자만 달라도 와일드카드(`"*"`)로 조용히 떨어진다 — 한도가 안 걸리는데
에러도 플래그도 안 난다. `check_table_keys()`가 시드마다 대조한다.
"""
from .models import JobTitle, Position

# ── 직책 (권위 축) — 「법인카드 사용 규정」 별표1의 행이 곧 이 목록이다 ─────────────
#  rank는 결재선 비교용. "부서장 이상 승인"을 이름 비교로 쓰면 체계가 바뀔 때 룰을 전부
#  고쳐야 한다 — DSL은 스칼라 비교만 하므로 숫자 축이 필요하다.
#
#  `비직책자(공용카드)`는 별표1이 쓰는 표기 그대로다. "직책 없음"을 뜻하지만 표의 키라서
#  이름을 바꾸면 룩업이 깨진다. rank 0 = 결재권 없음(팀장 이상만 관리자, 규정 제2조3).
JOB_TITLES: list[tuple[str, str, int]] = [
    ("NONE", "비직책자(공용카드)", 0),
    ("TEAM_LEAD", "팀장", 10),
    ("DEPT_HEAD", "부서장", 20),
    ("DIVISION_HEAD", "본부장", 30),
    ("CEO", "대표이사", 40),
]

# ── 직급 (처우 축) — 「직급체계」 §2 직급표 10단계. **판정에 쓰지 않는다.** ──────────
#  `assignable`은 그 직급이 보임 가능한 직책(직급표 마지막 열). 사람에게 직책을 배정할 때
#  경고용이지 강제 제약이 아니다 — 발령이 규정을 앞서는 실무가 있고, 강제하면 그런 건을
#  시스템에 아예 기록할 수 없게 된다.
POSITIONS: list[tuple[str, str, int, tuple[str, ...]]] = [
    ("STAFF", "사원", 10, ()),
    ("SENIOR_STAFF", "주임", 20, ()),
    ("ASSISTANT_MANAGER", "대리", 30, ()),
    ("MANAGER", "과장", 40, ("팀장",)),
    ("DEPUTY_GM", "차장", 50, ("팀장",)),
    ("GENERAL_MANAGER", "부장", 60, ("팀장", "부서장")),
    # 이사는 직급과 직책이 어긋날 수 있는 유일한 구간이다(별표1 각주 · 「직급체계」 §1.3).
    ("DIRECTOR", "이사", 70, ("부서장", "본부장")),
    ("SENIOR_DIRECTOR", "상무", 80, ("본부장",)),
    ("EXEC_DIRECTOR", "전무", 90, ("본부장",)),
    ("CEO", "대표이사", 100, ("대표이사",)),
]


def seed_org_codes() -> tuple[int, int]:
    """직책·직급 코드를 멱등 적재한다. Returns (직책 수, 직급 수).

    `code`가 키다 — 표기(`name`)를 고쳐도 사람에 붙은 FK가 끊기지 않는다.
    """
    for code, name, rank in JOB_TITLES:
        JobTitle.objects.update_or_create(code=code, defaults={"name": name, "rank": rank})
    for code, name, rank, assignable in POSITIONS:
        Position.objects.update_or_create(
            code=code, defaults={"name": name, "rank": rank, "assignable_titles": list(assignable)},
        )
    return JobTitle.objects.count(), Position.objects.count()


def check_table_keys() -> dict[str, list[str]]:
    """별표가 쓰는 축 값 중 **코드 테이블에 없는 이름**을 찾아 돌려준다.

    조용한 와일드카드 폴백이 이 시스템에서 가장 잡기 어려운 종류의 결함이다 —
    한도 룰이 안 걸리는데 에러도, 플래그도 없다. 시드가 끝나고 한 번 대조한다.
    """
    from domain.policies.tiger_tables import TABLES

    known = {
        "user.job_title": set(JobTitle.objects.values_list("name", flat=True)),
        "user.position": set(Position.objects.values_list("name", flat=True)),
    }
    missing: dict[str, list[str]] = {}
    for table in TABLES:
        axes = table.get("key_axes") or []
        if len(axes) != 1 or axes[0] not in known:
            continue
        unknown = sorted(k for k in table["payload"] if k != "*" and k not in known[axes[0]])
        if unknown:
            missing[table["key"]] = unknown
    return missing
