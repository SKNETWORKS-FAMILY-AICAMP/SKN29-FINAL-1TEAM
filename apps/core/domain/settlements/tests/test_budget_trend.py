"""예산 다개월 추세·과부족 패턴 회귀.

고정하는 계약 넷:

① **「0원」과 「데이터 없음」은 다르다.** 정산이 한 건도 없는 달은 `null`이다 — 0으로 채우면
   이력이 3개월뿐인데도 13개월 그래프가 그려지고, 사람은 앞의 0을 「지출이 없었다」로,
   그 다음을 「급증」으로 읽는다.

② **귀속 월은 결제일이다.** 정산을 언제 올렸는지가 아니라 언제 썼는지로 예산을 잡는다.

③ **사용액의 정의가 화면마다 같다.** `budget.py` 한 곳에서 나오므로 S-02 팀 예산과
   S-08 추세가 같은 팀·같은 달에 다른 숫자를 보이지 않는다.

④ **집계 쿼리는 2회다.** 개월 수가 늘어도 늘지 않는다(N+1이 생기면 여기서 잡힌다).
"""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from domain.accounts.models import Capability, Team
from domain.cards.models import Card
from domain.settlements import budget as B
from domain.settlements.models import Settlement, TeamBudget
from domain.transactions.models import Transaction

User = get_user_model()
URL = "/api/team-budget/trend/"


class BudgetTrendTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="영업팀", bu="영업본부")
        self.other = Team.objects.create(name="개발팀", bu="기술본부")
        self.user = User.objects.create_user("acc", password="p", team=self.team)
        self.user.extra_capabilities = [Capability.ACCOUNTING_REVIEW]
        self.user.save()
        self.card = Card.objects.create(card_type="PERSONAL", name="c1", owner=self.user)
        self.client.force_login(self.user)
        self.today = timezone.localdate()

    def _settle(self, amount, *, when=None, category="식대", team=None, status="CONFIRMED"):
        ts = timezone.make_aware(
            timezone.datetime.combine(when or self.today, timezone.datetime.min.time().replace(hour=12)),
        ) if when else timezone.localtime()
        tx = Transaction.objects.create(card=self.card, merchant="식당", amount=amount, ts=ts)
        return Settlement.objects.create(
            transaction=tx, category=category, submitted_by=self.user,
            team=team or self.team, status=status,
        )

    def _months_ago(self, n: int) -> date:
        """n개월 전 같은 달의 15일 — 말일 경계에 걸리지 않게 중순으로 잡는다."""
        y, m = self.today.year, self.today.month - n
        while m <= 0:
            y, m = y - 1, m + 12
        return date(y, m, 15)

    # ── ① 모름과 0 ────────────────────────────────────────────────────────
    def test_정산이_없는_달은_null이다(self):
        self._settle(100_000)
        body = self.client.get(URL, {"months": 4}).json()
        self.assertEqual(len(body["months"]), 4)
        #  이번 달만 데이터가 있다 → 앞 3칸은 null.
        self.assertEqual(body["totals"][:3], [None, None, None])
        self.assertEqual(body["totals"][3], 100_000)
        self.assertEqual(body["dataMonths"], [self.today.strftime("%Y-%m")])

    def test_지출이_없는_분류는_0이고_null이_아니다(self):
        """그 달에 정산은 있는데 그 분류만 없는 것 — 「0원」이 맞다."""
        self._settle(100_000, category="식대")
        body = self.client.get(URL, {"months": 2}).json()
        self.assertIn("식대", body["categories"])
        self.assertEqual(body["spend"]["식대"][-1], 100_000)

    # ── ② 귀속 월 ─────────────────────────────────────────────────────────
    def test_귀속_월은_결제일이_정한다(self):
        two = self._months_ago(2)
        self._settle(70_000, when=two)
        self._settle(30_000)
        body = self.client.get(URL, {"months": 4}).json()
        idx = body["months"].index(two.strftime("%Y-%m"))
        self.assertEqual(body["totals"][idx], 70_000)
        self.assertEqual(body["totals"][-1], 30_000)

    def test_최종반려는_집계에서_빠진다(self):
        self._settle(50_000)
        self._settle(90_000, status="REJECT")
        self.assertEqual(self.client.get(URL, {"months": 2}).json()["totals"][-1], 50_000)

    def test_보완요청은_아직_살아_있는_건이라_포함한다(self):
        self._settle(50_000, status="RETURNED")
        self.assertEqual(self.client.get(URL, {"months": 2}).json()["totals"][-1], 50_000)

    # ── 팀 필터 ───────────────────────────────────────────────────────────
    def test_팀을_주면_그_팀만_집계한다(self):
        self._settle(50_000, team=self.team)
        self._settle(80_000, team=self.other)
        whole = self.client.get(URL, {"months": 2}).json()
        mine = self.client.get(URL, {"months": 2, "team": self.team.pk}).json()
        self.assertEqual(whole["totals"][-1], 130_000)
        self.assertEqual(mine["totals"][-1], 50_000)
        self.assertEqual(mine["team"], self.team.pk)

    # ── 과부족 패턴 ───────────────────────────────────────────────────────
    def test_한도가_있는_달만_과부족을_센다(self):
        """예산 행이 없는 달을 세면 「한도 0에 100% 초과」가 된다."""
        ym = self.today.strftime("%Y-%m")
        TeamBudget.objects.create(team=self.team, year_month=ym, category="식대",
                                  limit_amount=200_000)
        self._settle(50_000, category="식대")
        pattern = self.client.get(URL, {"months": 3, "window": 3}).json()["pattern"]
        row = next(r for r in pattern["surplus"] if r["category"] == "식대")
        self.assertEqual(row["windowMonths"], 1)      # 한도가 있던 달은 1개월뿐
        self.assertEqual(row["avgGapPct"], 75.0)      # (200,000-50,000)/200,000
        self.assertEqual(row["amount"], 150_000)

    def test_한도를_넘기면_부족으로_분류된다(self):
        ym = self.today.strftime("%Y-%m")
        TeamBudget.objects.create(team=self.team, year_month=ym, category="접대",
                                  limit_amount=100_000)
        self._settle(150_000, category="접대")
        pattern = self.client.get(URL, {"months": 3, "window": 3}).json()["pattern"]
        self.assertEqual([r["category"] for r in pattern["short"]], ["접대"])
        self.assertEqual(pattern["short"][0]["amount"], -50_000)

    def test_한도가_없으면_어느_쪽에도_안_들어간다(self):
        self._settle(150_000, category="접대")
        pattern = self.client.get(URL, {"months": 3}).json()["pattern"]
        self.assertEqual(pattern["surplus"], [])
        self.assertEqual(pattern["short"], [])

    # ── 분류 목록 ─────────────────────────────────────────────────────────
    def test_값이_있는_분류만_내려준다(self):
        """전 분류를 내리면 한 번도 안 쓴 과목이 0선으로 그려지고, 사람은 그걸
        「지출이 0이었다」로 읽는다."""
        self._settle(10_000, category="식대")
        body = self.client.get(URL, {"months": 2}).json()
        self.assertEqual(body["categories"], ["식대"])

    # ── ③ 정의 일관성 ─────────────────────────────────────────────────────
    def test_추세와_팀예산_화면이_같은_숫자를_본다(self):
        self._settle(120_000, category="식대")
        ym = self.today.strftime("%Y-%m")
        trend = self.client.get(URL, {"months": 2}).json()["spend"]["식대"][-1]
        overview = self.client.get("/api/team-budget/overview/", {"month": ym}).json()
        team_row = next(t for t in overview["teams"] if t["id"] == self.team.pk)
        self.assertEqual(trend, team_row["used"])

    # ── ④ 쿼리 수 ─────────────────────────────────────────────────────────
    def test_개월_수가_늘어도_집계_쿼리는_2회다(self):
        for n in range(6):
            self._settle(10_000, when=self._months_ago(n))
        counts = []
        for months in (3, 24):
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(URL, {"months": months})
            #  세션·사용자 조회가 함께 잡히므로 SELECT 총량이 아니라 **개월 수에 따라
            #  늘지 않는다**를 본다(N+1이면 여기서 벌어진다).
            counts.append(len(ctx.captured_queries))
        self.assertEqual(counts[0], counts[1], f"개월 수에 따라 쿼리가 늘어난다: {counts}")

    def test_months_상한이_있다(self):
        """사용자가 주는 값이라 막지 않으면 전 기간을 훑는다."""
        body = self.client.get(URL, {"months": 9999}).json()
        self.assertLessEqual(len(body["months"]), 36)


class BudgetHelperTests(TestCase):
    """`months_with_data`는 사용액 결과에서 유도한다 — 쿼리를 따로 돌지 않는다."""

    def test_사용액_키에서_데이터_있는_달을_유도한다(self):
        spend = {("2026-06", "식대"): 100, ("2026-06", "회식"): 0, ("2026-08", ""): 50}
        self.assertEqual(B.months_with_data(spend), {"2026-06", "2026-08"})

    def test_recent_months는_연도_경계를_넘는다(self):
        months = B.recent_months(4, until=date(2026, 2, 10))
        self.assertEqual(months, ["2025-11", "2025-12", "2026-01", "2026-02"])
