"""신규 지출 등록 — **영수증 필수 + 실물 저장** 회귀.

## 왜 이 파일이 생겼나

화면이 `evidence: "OK"` 한 글자만 보내면 서버가 `receipts/<tx>.jpg`라는 **있지도 않은
경로**로 `Receipt`를 만들었다. 증빙이 있다고 기록됐지만 파일은 어디에도 없었고,
판정(`evidence.has_valid_receipt`)은 그걸 사실로 읽었으며, 비전 판독은 열 파일이 없어
돌 수 없었다.

고정하는 계약:
  ① **영수증 없이는 등록되지 않는다** — 증빙 없이 등록되면 판정이 곧바로 잡고 담당자는
     되돌려보낼 뿐이다. 그 왕복을 등록 단계에서 없앤다.
  ② 파일이 **실제로 저장된다** — `Receipt.file_ref`가 진짜 경로를 가리킨다.
  ③ 같은 파일이 `Attachment(RECEIPT)`로도 걸려 **판독이 예약된다**(업로드가 곧 판독 트리거).
  ④ 화면의 증빙 배지가 **실제 유무를 반영한다** — 예전엔 무조건 `OK`라 화면과 판정 사유가
     어긋나도 담당자가 설명할 수 없었다.
"""
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from domain.accounts.models import Role, Team, User
from domain.cards.models import Card, CardType
from domain.settlements.attachments import Attachment, AttachmentKind
from domain.settlements.models import Category, Settlement

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _file(name="receipt.png", content=PNG):
    return SimpleUploadedFile(name, content, content_type="image/png")


class CreateWithReceiptTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="영업팀", bu="영업본부")
        self.user = User.objects.create_user("kim", password="pw", role=Role.EMPLOYEE,
                                             team=self.team, first_name="김영업")
        self.card = Card.objects.create(card_type=CardType.PERSONAL, name="내 카드", owner=self.user)
        self.postpaid = Card.objects.create(card_type=CardType.POST_PAID, name="개인카드 후정산")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _payload(self, **over):
        base = {
            "merchant": "강남한식당", "amount": "45000", "date": "2026-08-20",
            "cardId": self.card.id, "category": Category.MEAL, "purpose": "팀 점심",
        }
        base.update(over)
        return base

    # ① 필수
    def test_영수증_없이는_등록되지_않는다(self):
        r = self.client.post("/api/settlements/", self._payload(), format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertIn("영수증", r.json()["detail"])
        self.assertFalse(Settlement.objects.exists())

    def test_evidence_문자열만으로는_통과하지_못한다(self):
        """예전에 있지도 않은 파일로 Receipt를 만들던 그 경로다."""
        r = self.client.post("/api/settlements/", self._payload(evidence="OK"), format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_지원하지_않는_형식은_400(self):
        r = self.client.post(
            "/api/settlements/", {**self._payload(), "receipt": _file("memo.txt", b"hi")},
            format="multipart",
        )
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Settlement.objects.exists())

    # ②③ 실물 저장 + 판독 예약
    def test_영수증이_실제로_저장되고_판독이_예약된다(self):
        with patch("domain.settlements.evidence_extract.run") as run:
            with self.captureOnCommitCallbacks(execute=True):
                r = self.client.post(
                    "/api/settlements/", {**self._payload(), "receipt": _file()}, format="multipart",
                )
            self.assertEqual(r.status_code, 201)
            run.assert_called_once()

        settlement = Settlement.objects.get()
        attachment = Attachment.objects.get()
        self.assertEqual(attachment.kind, AttachmentKind.RECEIPT)
        self.assertEqual(attachment.original_name, "receipt.png")

        receipt = settlement.transaction.receipts.get()
        #  **진짜 경로**를 가리킨다 — 예전엔 `receipts/<tx>.jpg`라는 없는 경로였다.
        self.assertEqual(receipt.file_ref, attachment.file_ref)
        self.assertTrue(receipt.file_ref.startswith("attachments/"))
        self.assertNotIn(f"receipts/{settlement.transaction_id}", receipt.file_ref)

    # ④ 배지가 사실을 반영한다
    def test_증빙_배지가_실제_유무를_따른다(self):
        with patch("domain.settlements.evidence_extract.run"):
            with self.captureOnCommitCallbacks(execute=True):
                created = self.client.post(
                    "/api/settlements/", {**self._payload(), "receipt": _file()}, format="multipart",
                ).json()
        self.assertEqual(created["evidence"], "OK")

        #  「내역 불러오기」로 들어온 건은 영수증이 없다 — 그대로 MISSING이어야 한다.
        settlement = Settlement.objects.get()
        settlement.transaction.receipts.all().delete()
        listed = self.client.get(f"/api/settlements/{settlement.id}/").json()
        self.assertEqual(listed["evidence"], "MISSING")

    # 후정산 카드
    def test_개인카드_후정산도_고를_수_있다(self):
        """법인카드를 못 쓰는 자리(해외·소액·긴급)에서 실제로 쓰인다 — 선택지에 있어야 한다."""
        names = {c["name"] for c in self.client.get("/api/cards/mine/").json()}
        self.assertIn("개인카드 후정산", names)

        with patch("domain.settlements.evidence_extract.run"):
            with self.captureOnCommitCallbacks(execute=True):
                created = self.client.post(
                    "/api/settlements/",
                    {**self._payload(cardId=self.postpaid.id), "receipt": _file()},
                    format="multipart",
                ).json()
        self.assertEqual(created["cardId"], self.postpaid.id)
        self.assertEqual(created["cardType"], CardType.POST_PAID)


class ActualUserOnCreateTests(TestCase):
    """**등록하는 행위 자체가 「내가 썼다」는 기록**이다.

    이게 없던 동안 본인이 팀·공용카드로 올린 건이 전부 `actual_user_recorded=None`(모름)으로
    남아, 기본 게이트의 `ACTUAL_USER_REQUIRED`에 걸리고 자동 통과에서 빠졌다(2026-08-24 실측).

    「내역 불러오기」(`erp_import`)가 팀·공용카드를 비워 두는 것과 **정반대 상황**이다 —
    그쪽은 카드사 원장에서 긁어와 주인을 모르는 건이라 `claim()`으로 해소해야 하지만,
    이쪽은 그 해소가 등록 시점에 이미 끝나 있다.
    """

    def setUp(self):
        self.team = Team.objects.create(name="영업팀", bu="영업본부")
        self.user = User.objects.create_user("kim", password="pw", role=Role.EMPLOYEE,
                                             team=self.team, first_name="김영업")
        self.cards = {
            CardType.PERSONAL: Card.objects.create(card_type=CardType.PERSONAL, owner=self.user),
            CardType.TEAM: Card.objects.create(card_type=CardType.TEAM, team=self.team),
            CardType.SHARED: Card.objects.create(card_type=CardType.SHARED, team=self.team),
        }
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _create(self, card):
        with patch("domain.settlements.evidence_extract.schedule"):
            return self.client.post("/api/settlements/", {
                "merchant": "강남한식당", "amount": "45000", "date": "2026-08-20",
                "cardId": card.id, "category": Category.MEAL, "purpose": "팀 점심",
                "receipt": _file(),
            }, format="multipart")

    def test_카드_구분과_무관하게_등록자가_실사용자다(self):
        for card_type, card in self.cards.items():
            with self.subTest(card_type=card_type):
                r = self._create(card)
                self.assertEqual(r.status_code, 201)
                s = Settlement.objects.get(pk=r.data["id"])
                self.assertEqual(s.actual_user_id, self.user.id)
                self.assertTrue(s.actual_user_recorded)

    def test_판정이_실사용자를_사실로_읽는다(self):
        """공용카드가 핵심이다 — 여기가 `None`이면 게이트가 `ACTUAL_USER_REQUIRED`를 건다."""
        from domain.policies.context_builder import build_rule_context

        s = Settlement.objects.get(pk=self._create(self.cards[CardType.SHARED]).data["id"])
        ctx, _ = build_rule_context(settlement=s)
        self.assertIs(ctx["card"]["actual_user_recorded"], True)
        self.assertIs(ctx["card"]["actual_user_is_spender"], True)

    def test_개인카드의_두_사실이_서로_다른_말을_하지_않는다(self):
        """예전엔 `recorded`만 카드 구분으로 보정받고 `is_spender`는 `None`으로 남았다."""
        from domain.policies.context_builder import build_rule_context

        s = Settlement.objects.get(pk=self._create(self.cards[CardType.PERSONAL]).data["id"])
        s.actual_user = None          # 옛 데이터 재현(백필 이전 상태)
        s.actual_user_recorded = None
        s.save(update_fields=["actual_user", "actual_user_recorded"])

        ctx, _ = build_rule_context(settlement=s)
        self.assertIs(ctx["card"]["actual_user_recorded"], True)
        self.assertIs(ctx["card"]["actual_user_is_spender"], True)

    def test_수집한_미귀속_건은_여전히_모름이다(self):
        """`erp_import`가 비워 두는 건 **설계**다 — 여기서 채우면 판정 사실을 지어내는 것."""
        from decimal import Decimal

        from django.utils import timezone

        from domain.policies.context_builder import build_rule_context
        from domain.transactions.models import Transaction

        tx = Transaction.objects.create(card=self.cards[CardType.SHARED], merchant="주점",
                                        amount=Decimal("120000"), ts=timezone.now())
        s = Settlement.objects.create(transaction=tx, submitted_by=None, team=self.team,
                                      status="DRAFT", category=Category.GATHERING)
        ctx, _ = build_rule_context(settlement=s)
        self.assertIsNone(ctx["card"]["actual_user_recorded"])
        self.assertIsNone(ctx["card"]["actual_user_is_spender"])
