"""증빙 첨부 업로드 → 판독 연동 회귀.

고정하는 계약:
  ① **업로드가 곧 판독 트리거**다 — 별도 버튼이 없다(있으면 아무도 안 누른다).
  ② **판독은 커밋 후** 돈다 — 업로드 트랜잭션이 60초짜리 AI 호출을 붙들지 않고,
     판독이 실패해도 **업로드는 살아남는다**(파일을 받아 놓고 기록이 사라지는 게 제일 나쁘다).
  ③ ai가 준 상태를 **그대로** 저장한다 — 뽑을 사실이 정의되지 않은 종류는 `SKIPPED`다.
     여기서 DONE으로 바꿔치면 "판독했다"는 거짓이 남는다.
  ④ 관측 계약을 깨지 않는다 — 빈 결과를 0/False로 채우지 않는다.
  ⑤ 비전 판독기가 여는 형식만 받는다(형식·용량 검증).
"""
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from domain.accounts.models import Role, Team, User
from domain.cards.models import Card, CardType
from domain.settlements.attachments import Attachment, AttachmentKind, ExtractionStatus
from domain.settlements.models import Settlement, SettlementStatus
from domain.transactions.models import Transaction

PDF = b"%PDF-1.4 fake"


def _upload(name="approval.pdf", content=PDF):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


class AttachmentUploadTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="영업팀", bu="영업본부")
        self.user = User.objects.create_user("kim", password="pw", role=Role.EMPLOYEE,
                                             team=self.team, first_name="김영업")
        card = Card.objects.create(card_type=CardType.PERSONAL, owner=self.user)
        tx = Transaction.objects.create(card=card, merchant="한식당", amount=120_000, ts=timezone.now())
        self.settlement = Settlement.objects.create(
            transaction=tx, submitted_by=self.user, team=self.team, status=SettlementStatus.DRAFT,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = f"/api/settlements/{self.settlement.id}/attachments/"

    # ① 업로드가 판독을 예약한다
    def test_업로드하면_판독이_예약된다(self):
        with patch("domain.settlements.evidence_extract.run") as run:
            with self.captureOnCommitCallbacks(execute=True):
                r = self.client.post(self.url, {"file": _upload(), "kind": "PRE_APPROVAL"},
                                     format="multipart")
            self.assertEqual(r.status_code, 201)
            run.assert_called_once()

        att = Attachment.objects.get()
        self.assertEqual(att.kind, AttachmentKind.PRE_APPROVAL)
        self.assertEqual(att.original_name, "approval.pdf")
        # ai가 열 수 있도록 **볼륨 기준 상대경로**여야 한다(절대경로는 `app/media.py`가 거부한다).
        self.assertTrue(att.file_ref)
        self.assertFalse(att.file_ref.startswith("/"))

    # ② 판독 실패가 업로드를 되돌리지 않는다
    def test_판독이_실패해도_첨부는_남는다(self):
        with patch("domain.settlements.evidence_extract.httpx.post", side_effect=RuntimeError("ai down")):
            with self.captureOnCommitCallbacks(execute=True):
                r = self.client.post(self.url, {"file": _upload(), "kind": "PRE_APPROVAL"},
                                     format="multipart")
        self.assertEqual(r.status_code, 201)
        att = Attachment.objects.get()
        self.assertEqual(att.extraction_status, ExtractionStatus.FAILED)
        self.assertIn("ai down", att.error)

    # ③④ ai 응답을 그대로 저장한다
    def test_판독_결과를_그대로_저장한다(self):
        payload = {
            "extraction_status": "DONE",
            "extracted": {"approval.pre_approval_obtained": True},
            "field_confidence": {"approval.pre_approval_obtained": 0.94},
            "evidence_spans": [{"path": "approval.pre_approval_obtained", "quote": "승인 완료"}],
            "extractor_version": "v1",
            "warnings": [],
        }
        with patch("domain.settlements.evidence_extract.httpx.post") as post:
            post.return_value.json.return_value = payload
            post.return_value.raise_for_status.return_value = None
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(self.url, {"file": _upload(), "kind": "PRE_APPROVAL"}, format="multipart")

        att = Attachment.objects.get()
        self.assertEqual(att.extraction_status, ExtractionStatus.DONE)
        self.assertEqual(att.extracted, {"approval.pre_approval_obtained": True})
        self.assertEqual(att.extractor_version, "v1")
        self.assertIsNotNone(att.extracted_at)

    def test_추출_대상이_아닌_종류는_SKIPPED로_남는다(self):
        """계약서·기타는 뽑을 사실이 정의돼 있지 않다. DONE으로 바꿔치면 거짓이 된다."""
        payload = {"extraction_status": "SKIPPED", "extracted": {}, "field_confidence": {},
                   "evidence_spans": [], "extractor_version": "v1",
                   "warnings": ["`CONTRACT`는 추출 대상 종류가 아닙니다"]}
        with patch("domain.settlements.evidence_extract.httpx.post") as post:
            post.return_value.json.return_value = payload
            post.return_value.raise_for_status.return_value = None
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(self.url, {"file": _upload("contract.pdf"), "kind": "CONTRACT"},
                                 format="multipart")

        att = Attachment.objects.get()
        self.assertEqual(att.extraction_status, ExtractionStatus.SKIPPED)
        # 관측 계약: 빈 결과를 0/False로 채우지 않는다.
        self.assertEqual(att.extracted, {})

    # ⑤ 입력 검증
    def test_지원하지_않는_형식은_400(self):
        r = self.client.post(self.url, {"file": _upload("memo.txt", b"hello"), "kind": "OTHER"},
                             format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Attachment.objects.count(), 0)

    def test_알_수_없는_종류는_400(self):
        r = self.client.post(self.url, {"file": _upload(), "kind": "NOPE"}, format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_파일이_없으면_400(self):
        self.assertEqual(self.client.post(self.url, {"kind": "OTHER"}, format="multipart").status_code, 400)

    # 목록·삭제·재시도
    def test_목록과_삭제(self):
        with patch("domain.settlements.evidence_extract.run"):
            with self.captureOnCommitCallbacks(execute=True):
                created = self.client.post(self.url, {"file": _upload(), "kind": "OTHER"},
                                           format="multipart").json()
        rows = self.client.get(self.url).json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kindLabel"], "기타")

        self.assertEqual(self.client.delete(f"{self.url}{created['id']}/").status_code, 204)
        self.assertEqual(Attachment.objects.count(), 0)

    def test_판독_재시도는_다시_예약한다(self):
        with patch("domain.settlements.evidence_extract.run"):
            with self.captureOnCommitCallbacks(execute=True):
                created = self.client.post(self.url, {"file": _upload(), "kind": "PRE_APPROVAL"},
                                           format="multipart").json()
        with patch("domain.settlements.evidence_extract.run") as run:
            with self.captureOnCommitCallbacks(execute=True):
                r = self.client.post(f"{self.url}{created['id']}/reextract/", {}, format="json")
            self.assertEqual(r.status_code, 200)
            run.assert_called_once()
