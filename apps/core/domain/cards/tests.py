"""법인카드 관리(S-09) API 회귀.

고정하는 계약:
  ① **사용액은 저장하지 않는다** — 그 달 실제 결제 합계로 계산한다(`TeamBudget`과 같은 규율).
  ② **"회수 필요"는 저장하지 않는다** — 퇴사·반복 이상사용에서 파생된다. 컬럼으로 굳히면
     원인이 사라져도 표시가 남는다.
  ③ **배정은 서로를 지운다** — 팀 배정과 개인 배정이 동시에 채워지면 귀속이 모호해진다.
  ④ **정지에는 사유가 필수** — "왜 정지됐지"를 묻는 사람이 반드시 나온다.
  ⑤ 인가는 `accounting_review`.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from domain.accounts.models import Role, Team, User
from domain.cards.models import Card, CardStatus, CardType
from domain.cards.views import ANOMALY_MIN_COUNT
from domain.transactions.models import Transaction


class CardApiTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="영업팀", bu="영업본부")
        self.other_team = Team.objects.create(name="재무회계팀", bu="경영지원본부")
        self.acc = User.objects.create_user("acc", password="pw", role=Role.ACCOUNTANT,
                                            team=self.other_team, first_name="박회계")
        self.emp = User.objects.create_user("kim", password="pw", role=Role.EMPLOYEE,
                                            team=self.team, first_name="김영업")
        self.card = Card.objects.create(card_type=CardType.PERSONAL, name="개인카드",
                                        number_masked="**** 1001", owner=self.emp,
                                        limit_amount=1_500_000)
        self.client = APIClient()
        self.client.force_authenticate(self.acc)

    def _tx(self, merchant="한식당", amount=10_000, when=None):
        return Transaction.objects.create(
            card=self.card, merchant=merchant, amount=amount, ts=when or timezone.now(),
        )

    # ① 사용액 = 그 달 실제 결제 합계
    def test_사용액은_이번달_거래_합계로_계산된다(self):
        self._tx(amount=30_000)
        self._tx(amount=20_000)
        # 지난달 거래는 이번 달 사용액에 들어가지 않는다.
        self._tx(amount=99_000, when=timezone.now() - timedelta(days=45))
        row = self.client.get("/api/cards/").json()["cards"][0]
        self.assertEqual(row["usage"], 50_000)
        self.assertEqual(row["limit"], 1_500_000)

    # ② "회수 필요"는 파생
    def test_퇴사자_카드는_조치대상으로_뜬다(self):
        self.emp.is_active = False
        self.emp.save(update_fields=["is_active"])
        body = self.client.get("/api/cards/attention/").json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["groups"][0]["reason"], "RETIRED_OWNER")

    def test_퇴사가_취소되면_조치대상에서_사라진다(self):
        """저장된 상태였다면 남았을 것이다 — 파생이라 원인이 사라지면 같이 사라진다."""
        self.emp.is_active = False
        self.emp.save(update_fields=["is_active"])
        self.assertEqual(self.client.get("/api/cards/attention/").json()["total"], 1)
        self.emp.is_active = True
        self.emp.save(update_fields=["is_active"])
        self.assertEqual(self.client.get("/api/cards/attention/").json()["total"], 0)

    def test_같은_가맹점_반복결제가_임계값을_넘으면_조치대상(self):
        for _ in range(ANOMALY_MIN_COUNT):
            self._tx(merchant="수상한 가맹점")
        body = self.client.get("/api/cards/attention/").json()
        self.assertEqual(body["groups"][0]["reason"], "REPEAT_ANOMALY")
        # 판정 기준을 응답에 실어 화면이 그대로 표기하게 한다(근거를 숨기지 않는다).
        self.assertEqual(body["anomalyRule"]["minCount"], ANOMALY_MIN_COUNT)

    def test_임계값_미만이면_조치대상이_아니다(self):
        for _ in range(ANOMALY_MIN_COUNT - 1):
            self._tx(merchant="수상한 가맹점")
        self.assertEqual(self.client.get("/api/cards/attention/").json()["total"], 0)

    def test_정지된_카드는_조치대상에서_빠진다(self):
        self.emp.is_active = False
        self.emp.save(update_fields=["is_active"])
        self.client.post(f"/api/cards/{self.card.id}/stop/", {"reason": "퇴사 처리"}, format="json")
        self.assertEqual(self.client.get("/api/cards/attention/").json()["total"], 0)

    # ③ 배정은 서로를 지운다
    def test_팀_배정은_개인_배정을_지운다(self):
        r = self.client.post(f"/api/cards/{self.card.id}/assign/",
                             {"mode": "TEAM", "teamId": self.team.id, "reason": "부서 이동"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.card.refresh_from_db()
        self.assertEqual(self.card.card_type, CardType.TEAM)
        self.assertIsNone(self.card.owner_id)
        self.assertEqual(self.card.team_id, self.team.id)

    def test_개인_배정은_팀_카드를_그_사람_소유로_바꾼다(self):
        self.card.card_type, self.card.owner, self.card.team = CardType.TEAM, None, self.team
        self.card.save()
        r = self.client.post(f"/api/cards/{self.card.id}/assign/",
                             {"mode": "PERSONAL", "userId": self.emp.id, "reason": "재배정"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.card.refresh_from_db()
        self.assertEqual(self.card.owner_id, self.emp.id)
        self.assertEqual(self.card.card_type, CardType.PERSONAL)

    def test_없는_대상으로_배정하면_400(self):
        r = self.client.post(f"/api/cards/{self.card.id}/assign/",
                             {"mode": "TEAM", "teamId": 999999}, format="json")
        self.assertEqual(r.status_code, 400)

    # ④ 정지 사유 필수
    def test_사유_없는_정지는_400(self):
        r = self.client.post(f"/api/cards/{self.card.id}/stop/", {"reason": "  "}, format="json")
        self.assertEqual(r.status_code, 400)
        self.card.refresh_from_db()
        self.assertEqual(self.card.status, CardStatus.ACTIVE)

    def test_정지는_사유와_시각을_남긴다(self):
        r = self.client.post(f"/api/cards/{self.card.id}/stop/",
                             {"reason": "퇴사 처리 — 회수 완료"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.card.refresh_from_db()
        self.assertEqual(self.card.status, CardStatus.STOPPED)
        self.assertIn("퇴사", self.card.stopped_reason)
        self.assertIsNotNone(self.card.stopped_at)
        self.assertEqual(self.card.stopped_by_id, self.acc.id)

    def test_정지해제는_사유_기록을_지우지_않는다(self):
        self.client.post(f"/api/cards/{self.card.id}/stop/", {"reason": "오인 정지"}, format="json")
        self.client.post(f"/api/cards/{self.card.id}/reactivate/", {}, format="json")
        self.card.refresh_from_db()
        self.assertEqual(self.card.status, CardStatus.ACTIVE)
        self.assertEqual(self.card.stopped_reason, "오인 정지")   # 무슨 일이 있었는지가 지워지면 안 된다

    # ⑤ 인가
    def test_권한_없는_사용자는_403(self):
        c = APIClient()
        c.force_authenticate(self.emp)
        self.assertEqual(c.get("/api/cards/").status_code, 403)

    def test_익명은_403(self):
        self.assertEqual(APIClient().get("/api/cards/").status_code, 403)
