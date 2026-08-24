"""예산 집계 — **사용액의 정의를 한 곳에만 둔다**.

## 왜 모으는가

「사용액」의 정의는 세 조각이다: ① 최종반려(`REJECT`)는 제외 ② 귀속 월은 **결제일**
(`transaction.ts`)이 정한다 ③ 금액은 카드 전표 금액 합계. 이 셋이 화면마다 조금씩 달라지면
S-02 팀 예산과 S-08 예산 관리가 **같은 팀·같은 달에 다른 숫자**를 보여준다.

원래 두 뷰(`TeamBudgetView`·`TeamBudgetOverviewView`)가 같은 로직을 각자 들고 있었고,
추세 집계가 세 번째 사본이 될 자리였다. 그래서 여기로 모았다.

## 왜 DB 뷰·CTE를 쓰지 않는가

다개월 추세도 **GROUP BY 두 번**으로 끝난다(사용액 1회 + 한도 1회). 13개월 × 분류 6종 =
78칸이고, 과부족 판정은 두 dict를 맞대면 되는 산수다. 여기에 뷰나 재귀 CTE를 넣으면
**「사용액이 무엇인가」가 파이썬과 SQL 두 곳에 생긴다** — 위 세 조각이 갈라질 자리를
하나 더 만드는 셈이고, 이 저장소가 반복해서 잡아온 결함이 정확히 그 부류다.

성능이 문제가 되는 규모(수십만 행 × 수십 개월)가 오면 그때는 **집계 테이블**이 답이지
뷰가 아니다 — 뷰는 매번 원본을 다시 훑는다.
"""
from __future__ import annotations

from datetime import date

from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

#: 최종반려는 집행되지 않은 돈이다. 보완요청(`RETURNED`)은 아직 살아 있는 건이라 포함한다.
BUDGET_EXCLUDE = ("REJECT",)


def month_key(value: date) -> str:
    return value.strftime("%Y-%m")


def recent_months(count: int, *, until: date | None = None) -> list[str]:
    """`until`이 속한 달을 **마지막**으로 하는 `YYYY-MM` 목록(오래된 순)."""
    end = until or timezone.localdate()
    year, month = end.year, end.month
    out: list[str] = []
    for _ in range(count):
        out.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return list(reversed(out))


def monthly_spend(months: list[str], *, team_id: int | None = None) -> dict[tuple[str, str], int]:
    """`(YYYY-MM, 비용분류) → 사용액(원)`. **쿼리 1회.**

    귀속 월은 결제일(`transaction.ts`)이다 — 정산을 언제 올렸는지가 아니라 **언제 썼는지**로
    예산을 잡는다(월말에 몰아 제출하면 지난달 예산이 이번 달로 넘어와 버린다).
    """
    if not months:
        return {}
    from .models import Settlement

    qs = (
        Settlement.objects
        .exclude(status__in=BUDGET_EXCLUDE)
        .filter(transaction__isnull=False)
        # 범위를 좁혀 준다 — 전 기간을 훑고 파이썬에서 버리면 행이 쌓일수록 느려진다.
        .filter(transaction__ts__date__gte=date(int(months[0][:4]), int(months[0][5:7]), 1))
    )
    if team_id is not None:
        qs = qs.filter(team_id=team_id)

    wanted = set(months)
    out: dict[tuple[str, str], int] = {}
    rows = (
        qs.annotate(ym=TruncMonth("transaction__ts"))
        .values("ym", "category")
        .annotate(total=Sum("transaction__amount"))
    )
    for row in rows:
        if row["ym"] is None:
            continue
        key = month_key(timezone.localtime(row["ym"]).date()
                        if timezone.is_aware(row["ym"]) else row["ym"])
        if key in wanted:
            out[(key, row["category"] or "")] = int(row["total"] or 0)
    return out


def months_with_data(spend: dict[tuple[str, str], int]) -> set[str]:
    """정산이 **한 건이라도 있는** 달. 「0원」과 「데이터 없음」을 가르는 데 쓴다.

    없으면 안 되는 구분이다: 이력이 3개월뿐인데 13개월 그래프를 0으로 채우면 사람은 그걸
    「지출이 없었다」로 읽고, 그 다음 달을 「급증」으로 읽는다. EvalContext가 `None`과 `0`을
    가르는 것과 같은 이유다.

    **쿼리를 따로 돌지 않는다** — `monthly_spend()`가 정산 하나를 반드시 어느 (월, 분류)
    칸에 넣으므로, 키에 있는 달이 곧 데이터가 있는 달이다. 따로 세면 쿼리가 하나 늘고
    두 정의(같은 필터를 두 번 적음)가 갈라질 자리가 생긴다.
    """
    return {ym for (ym, _) in spend}


def monthly_limits(months: list[str], *, team_id: int | None = None) -> dict[tuple[str, str], int]:
    """`(YYYY-MM, 비용분류) → 한도(원)`. **쿼리 1회.**

    `category=""` 행은 팀 총한도다 — 과목 합과 다른 축이라 그대로 남긴다(불변식은
    `TeamBudget` 모델 docstring).
    """
    if not months:
        return {}
    from .models import TeamBudget

    qs = TeamBudget.objects.filter(year_month__in=months)
    if team_id is not None:
        qs = qs.filter(team_id=team_id)
    out: dict[tuple[str, str], int] = {}
    for row in qs.values("year_month", "category").annotate(total=Sum("limit_amount")):
        out[(row["year_month"], row["category"] or "")] = int(row["total"] or 0)
    return out


def spend_by_team(month: str) -> dict[tuple[int, str], int]:
    """`(team_id, 비용분류) → 사용액(원)` — 한 달치. 팀별 화면 두 곳이 쓴다."""
    from .models import Settlement

    qs = Settlement.objects.exclude(status__in=BUDGET_EXCLUDE)
    if "-" in month:
        year, mon = month.split("-")[:2]
        qs = qs.filter(transaction__ts__year=int(year), transaction__ts__month=int(mon))
    return {
        (row["team_id"], row["category"] or ""): int(row["s"] or 0)
        for row in qs.values("team_id", "category").annotate(s=Sum("transaction__amount"))
        if row["team_id"]
    }


def gap_pattern(
    months: list[str], categories: list[str],
    spend: dict[tuple[str, str], int], limits: dict[tuple[str, str], int],
) -> dict[str, list[dict]]:
    """「자주 남는다 / 자주 모자란다」 — 한도 산정 문제를 집행 문제와 가른다.

    한 달만 보면 우연이지만 **여섯 달 중 다섯 달 모자랐다면 그건 집행이 아니라 한도가
    틀린 것**이다. 그래서 개월 수를 함께 센다.

    **한도가 없는 달은 세지 않는다** — 예산 행이 없는 것과 한도가 0인 것은 다르다.
    안 세면 분모가 줄어 비율이 과장되지만, 넣으면 「한도 0에 100% 초과」가 되어 더 나쁘다.
    """
    surplus, short = [], []
    for cat in categories:
        gaps, amounts, counted = [], [], 0
        for ym in months:
            limit = limits.get((ym, cat))
            if not limit:
                continue
            counted += 1
            used = spend.get((ym, cat), 0)
            amounts.append(limit - used)
            gaps.append((limit - used) / limit * 100)
        if not counted:
            continue
        avg_gap = sum(gaps) / len(gaps)
        total_gap = sum(amounts)
        row = {
            "category": cat,
            #  과부족이 **같은 방향으로** 난 개월 수 — 평균만 보면 +50/-50이 0으로 상쇄된다.
            "months": sum(1 for g in gaps if (g > 0) == (avg_gap > 0)),
            "windowMonths": counted,
            "avgGapPct": round(avg_gap, 1),
            "amount": total_gap,
        }
        (surplus if avg_gap > 0 else short).append(row)

    surplus.sort(key=lambda r: -r["avgGapPct"])
    short.sort(key=lambda r: r["avgGapPct"])
    return {"surplus": surplus, "short": short}
