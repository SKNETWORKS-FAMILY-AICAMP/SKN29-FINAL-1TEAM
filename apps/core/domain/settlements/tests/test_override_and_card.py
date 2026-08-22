"""승인대기 수동 재분류 + 카드 선택 회귀.

## 승인대기 되돌리기

룰이 통과시킨 건을 회계 담당자가 열어 보고 "이건 아니다"라고 판단하는 일이 실제로
생긴다. 확정만 허용하면 그 판단을 반영할 방법이 없어, 담당자는 잘못된 줄 알면서 확정하거나
그냥 둔다. 되돌릴 수 있게 하되 **이력에 「룰 통과 → 회계 재분류」로 남긴다** — 판정 이력과
사람의 결정을 구분해 남기지 않으면 룰 정밀도 집계가 사람 판단을 룰의 성과로 착각한다.

## 카드 선택

예전엔 화면이 카드 **구분**(개인/팀/공용)만 보냈고 서버가 그 구분의 `first()`를 붙였다 —
**남의 개인카드가 내 지출에 붙을 수 있었다.** 카드 귀속은 판정 사실(`card.card_type`·
`card.actual_user_recorded`)이 되므로 엉뚱한 카드는 그대로 오판이 된다.
"""
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from domain.accounts.models import Capability, Role, Team, User
from domain.cards.models import Card, CardStatus, CardType
from domain.settlements import services
from domain.settlements.models import Category, Settlement, SettlementStatus as S
from domain.transactions.models import Transaction


class PendingConfirmOverrideTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="영업팀", bu="영업본부")
        self.spender = User.objects.create_user("kim", password="pw", role=Role.EMPLOYEE,
                                                team=self.team, first_name="김영업")
        self.acc = User.objects.create_user("acc", password="pw", role=Role.ACCOUNTANT,
                                            team=self.team, first_name="박회계")
        card = Card.objects.create(card_type=CardType.PERSONAL, owner=self.spender)
        tx = Transaction.objects.create(card=card, merchant="카페", amount=Decimal("9000"),
                                        ts=timezone.now())
        self.settlement = Settlement.objects.create(
            transaction=tx, submitted_by=self.spender, team=self.team,
            status=S.PENDING_CONFIRM, category=Category.MEAL,
            rule_judgement={"decision": "PASS", "flags": []},
        )
        self.client = APIClient()
        self.client.force_authenticate(self.acc)

    def test_승인대기_건을_보완요청으로_되돌릴_수_있다(self):
        r = self.client.post(f"/api/settlements/{self.settlement.id}/review/",
                             {"decision": "RETURN", "reason": "증빙 누락 — 영수증을 첨부해 주세요."},
                             format="json")
        self.assertEqual(r.status_code, 200)
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, S.RETURNED)

    def test_승인대기_건을_반려할_수_있다(self):
        r = self.client.post(f"/api/settlements/{self.settlement.id}/review/",
                             {"decision": "REJECT", "reason": "사적 사용 의심"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, S.REJECT)

    def test_되돌리면_이력에_재분류_표시가_남는다(self):
        """"룰은 통과라고 했는데 왜 보완요청이 갔지"를 나중에 되짚을 수 있어야 한다."""
        self.client.post(f"/api/settlements/{self.settlement.id}/review/",
                         {"decision": "RETURN", "reason": "증빙 누락"}, format="json")
        event = self.settlement.events.order_by("-id").first()
        self.assertEqual((event.from_state, event.to_state), (S.PENDING_CONFIRM, S.RETURNED))
        self.assertIn(services.RULE_OVERRIDE_MARK, event.reason)
        self.assertIn("룰 판정=PASS", event.reason)   # 무엇을 뒤집었는지까지 남긴다
        self.assertIn("증빙 누락", event.reason)      # 사람이 쓴 사유도 그대로 남는다

    def test_검토중에서_내리는_결정에는_표시가_붙지_않는다(self):
        """IN_REVIEW의 보완요청은 뒤집는 게 아니라 **원래 맡겨진 판단**이다."""
        self.settlement.status = S.IN_REVIEW
        self.settlement.save(update_fields=["status"])
        self.client.post(f"/api/settlements/{self.settlement.id}/review/",
                         {"decision": "RETURN", "reason": "증빙 누락"}, format="json")
        event = self.settlement.events.order_by("-id").first()
        self.assertNotIn(services.RULE_OVERRIDE_MARK, event.reason)

    def test_확정_경로는_그대로_동작한다(self):
        r = self.client.post(f"/api/settlements/{self.settlement.id}/confirm/", {}, format="json")
        self.assertEqual(r.status_code, 200)
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, S.ERP_VOUCHER_DRAFTED)

    def test_사유_없는_되돌리기는_거부된다(self):
        r = self.client.post(f"/api/settlements/{self.settlement.id}/review/",
                             {"decision": "RETURN"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, S.PENDING_CONFIRM)


#: 신규 등록은 **영수증이 필수**다(`test_create_receipt.py`) — 카드 검증만 보려는
#  테스트도 파일을 함께 보내야 한다.
PNG = bytes([0x89]) + b"PNG" + bytes([13, 10, 26, 10]) + b"0" * 32


def _receipt():
    return SimpleUploadedFile("r.png", PNG, content_type="image/png")


class MyCardsTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="영업팀", bu="영업본부")
        self.other_team = Team.objects.create(name="AI·개발팀", bu="기술본부")
        self.user = User.objects.create_user("kim", password="pw", role=Role.EMPLOYEE,
                                             team=self.team, first_name="김영업")
        self.stranger = User.objects.create_user("park", password="pw", role=Role.EMPLOYEE,
                                                 team=self.other_team, first_name="박개발")
        self.mine = Card.objects.create(card_type=CardType.PERSONAL, name="내 개인카드", owner=self.user)
        self.team_card = Card.objects.create(card_type=CardType.TEAM, name="영업팀 팀카드", team=self.team)
        self.company = Card.objects.create(card_type=CardType.POST_PAID, name="후정산 청구")
        self.others = Card.objects.create(card_type=CardType.PERSONAL, name="남의 개인카드", owner=self.stranger)
        self.other_team_card = Card.objects.create(card_type=CardType.TEAM, name="개발팀 팀카드", team=self.other_team)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_내가_쓸_수_있는_카드만_보인다(self):
        rows = self.client.get("/api/cards/mine/").json()
        names = {r["name"] for r in rows}
        self.assertEqual(names, {"내 개인카드", "영업팀 팀카드", "후정산 청구"})
        self.assertNotIn("남의 개인카드", names)
        self.assertNotIn("개발팀 팀카드", names)

    def test_정지된_카드는_고를_수_없다(self):
        self.mine.status = CardStatus.STOPPED
        self.mine.save(update_fields=["status"])
        names = {r["name"] for r in self.client.get("/api/cards/mine/").json()}
        self.assertNotIn("내 개인카드", names)

    def test_회계_권한_없이도_조회된다(self):
        """지출 등록은 임직원 누구나 한다 — 회계 권한을 요구하면 등록 자체가 막힌다."""
        self.assertFalse(self.user.has_capability(Capability.ACCOUNTING_REVIEW))
        self.assertEqual(self.client.get("/api/cards/mine/").status_code, 200)

    def test_익명은_403(self):
        self.assertEqual(APIClient().get("/api/cards/mine/").status_code, 403)

    # ── 저장 경로: 목록만 좁히고 저장을 안 막으면 요청을 손댄 값이 그대로 들어간다
    def test_고른_카드가_그대로_붙는다(self):
        r = self.client.post("/api/settlements/", {
            "merchant": "카페", "amount": "9000", "date": "2026-08-20",
            "cardId": self.team_card.id, "category": Category.MEAL, "receipt": _receipt(),
        }, format="multipart")
        self.assertEqual(r.status_code, 201)
        settlement = Settlement.objects.get(pk=r.json()["id"])
        self.assertEqual(settlement.transaction.card_id, self.team_card.id)
        self.assertEqual(r.json()["cardId"], self.team_card.id)

    def test_남의_개인카드는_붙지_않는다(self):
        r = self.client.post("/api/settlements/", {
            "merchant": "카페", "amount": "9000", "date": "2026-08-20",
            "cardId": self.others.id, "category": Category.MEAL, "receipt": _receipt(),
        }, format="multipart")
        self.assertEqual(r.status_code, 201)
        settlement = Settlement.objects.get(pk=r.json()["id"])
        self.assertIsNone(settlement.transaction.card_id)   # 조용히 남의 카드를 붙이지 않는다

    def test_구분만_보내는_옛_호출도_본인_범위에서_고른다(self):
        """하위호환 — 그래도 `first()`로 아무 카드나 집지 않는다."""
        r = self.client.post("/api/settlements/", {
            "merchant": "카페", "amount": "9000", "date": "2026-08-20",
            "cardType": CardType.PERSONAL, "category": Category.MEAL, "receipt": _receipt(),
        }, format="multipart")
        settlement = Settlement.objects.get(pk=r.json()["id"])
        self.assertEqual(settlement.transaction.card_id, self.mine.id)

    def test_수정에서도_카드를_바꿀_수_있다(self):
        created = self.client.post("/api/settlements/", {
            "merchant": "카페", "amount": "9000", "date": "2026-08-20",
            "cardId": self.mine.id, "category": Category.MEAL, "receipt": _receipt(),
        }, format="multipart").json()
        r = self.client.patch(f"/api/settlements/{created['id']}/",
                              {"cardId": self.team_card.id}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["cardId"], self.team_card.id)

    def test_수정에서_남의_카드로_바꾸면_400(self):
        created = self.client.post("/api/settlements/", {
            "merchant": "카페", "amount": "9000", "date": "2026-08-20",
            "cardId": self.mine.id, "category": Category.MEAL, "receipt": _receipt(),
        }, format="multipart").json()
        r = self.client.patch(f"/api/settlements/{created['id']}/",
                              {"cardId": self.others.id}, format="json")
        self.assertEqual(r.status_code, 400)
