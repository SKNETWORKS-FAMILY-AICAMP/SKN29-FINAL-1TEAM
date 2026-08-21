"""전 팀 예산 현황(S-08) 회귀.

고정하는 계약:
  ① **한도만 DB, 사용액은 실 내역 집계** — `TeamBudgetView`와 같은 규약을 쓴다.
  ② **최종 반려(REJECT)만 제외** — 카드는 이미 결제됐으므로 진행 단계와 무관하게 사용액이다.
  ③ 예산 행이 없는 과목의 지출을 **숨기지 않는다** — 숨기면 "항목 합 ≠ 총 사용액"이
     원인 없이 어긋나 보인다.
  ④ 인가는 회계 검토 **또는** 거버넌스 열람(Sidebar의 `/budget` 조건과 같다).
"""
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from domain.accounts.models import Role, Team, User
from domain.cards.models import Card, CardType
from domain.settlements.models import Category, Settlement, SettlementStatus, TeamBudget
from domain.transactions.models import Transaction

URL = "/api/team-budget/overview/"


class BudgetOverviewTests(TestCase):
    def setUp(self):
        self.month = timezone.localdate().strftime("%Y-%m")
        self.team = Team.objects.create(name="영업팀", bu="영업본부")
        self.acc = User.objects.create_user("acc", password="pw", role=Role.ACCOUNTANT,
                                            team=self.team, first_name="박회계")
        self.emp = User.objects.create_user("kim", password="pw", role=Role.EMPLOYEE,
                                            team=self.team, first_name="김영업")
        self.card = Card.objects.create(card_type=CardType.TEAM, team=self.team)
        TeamBudget.objects.create(team=self.team, year_month=self.month, category="", limit_amount=3_000_000)
        TeamBudget.objects.create(team=self.team, year_month=self.month,
                                  category=Category.MEAL, limit_amount=1_000_000)
        self.client = APIClient()
        self.client.force_authenticate(self.acc)

    def _spend(self, amount, category, status=SettlementStatus.CONFIRMED):
        tx = Transaction.objects.create(card=self.card, merchant="한식당", amount=amount, ts=timezone.now())
        return Settlement.objects.create(transaction=tx, submitted_by=self.emp, team=self.team,
                                         category=category, status=status)

    def test_한도는_DB_사용액은_집계다(self):
        self._spend(400_000, Category.MEAL)
        team = self.client.get(URL).json()["teams"][0]
        self.assertEqual(team["total"], 3_000_000)
        self.assertEqual(team["categories"], [{"label": "식대", "limit": 1_000_000, "used": 400_000}])
        self.assertEqual(team["used"], 400_000)

    def test_최종반려만_사용액에서_빠진다(self):
        self._spend(100_000, Category.MEAL, SettlementStatus.IN_REVIEW)     # 진행 중이어도 사용액
        self._spend(500_000, Category.MEAL, SettlementStatus.REJECT)        # 최종 반려만 제외
        team = self.client.get(URL).json()["teams"][0]
        self.assertEqual(team["used"], 100_000)

    def test_예산행_없는_과목_지출은_따로_노출된다(self):
        self._spend(70_000, Category.TRIP)      # 출장 예산 행이 없다
        team = self.client.get(URL).json()["teams"][0]
        self.assertEqual(team["unbudgetedUsed"], 70_000)
        self.assertEqual(team["unbudgeted"], {"출장": 70_000})
        # 총 사용액에는 들어간다 — 그래서 화면이 "항목 합 ≠ 총액"을 설명할 수 있어야 한다.
        self.assertEqual(team["used"], 70_000)
        self.assertEqual(team["categories"][0]["used"], 0)

    def test_모든_팀이_내려온다(self):
        Team.objects.create(name="AI·개발팀", bu="기술본부")
        body = self.client.get(URL).json()
        self.assertEqual({t["name"] for t in body["teams"]}, {"영업팀", "AI·개발팀"})
        self.assertEqual(body["month"], self.month)

    def test_거버넌스_열람자도_볼_수_있다(self):
        exec_user = User.objects.create_user("exec", password="pw", role=Role.EXECUTIVE)
        c = APIClient()
        c.force_authenticate(exec_user)
        self.assertEqual(c.get(URL).status_code, 200)

    def test_일반_사용자는_403(self):
        c = APIClient()
        c.force_authenticate(self.emp)
        self.assertEqual(c.get(URL).status_code, 403)
