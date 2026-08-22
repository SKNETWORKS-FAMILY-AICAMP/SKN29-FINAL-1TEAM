"""Draft Agent 입력 묶음 + 제출 준비 회귀.

## 왜 이 파일이 생겼나

초안 Agent가 받는 외부 사실은 업종과 분류별 한도 **둘뿐**이었고, 나머지는 화면이 보낸
폼 값이었다. 그래서 모델이 지어낼 수 있는 자리가 넓었다. 그리고 「보완요청될 것 같은가」를
LLM에게 예측시키려는 유혹이 있었는데, 그 답은 결정론적 엔진이 이미 갖고 있다
(`orchestrator.judge(record=False)` — 이 용도로 만들어 두고 호출부가 없던 통로다).

고정하는 계약:
  ① 판정 미리보기는 **엔진 dry-run**이다 — `rule_hits`도 상태도 건드리지 않는다.
  ② 기본 내역·첨부 추출 사실·EvalContext가 한 번에 온다(모델이 따로 조회할 필요가 없다).
  ③ 보완요청으로 돌아온 건은 **왜 돌아왔는지**가 함께 온다.
  ④ 제출 준비는 `shouldConfirm`으로 「사람을 멈춰 세울지」를 서버가 정한다.
     REVIEW로는 멈추지 않는다(룰이 판단을 미룬 것뿐이고 회계가 보는 정상 경로다).
  ⑤ 영수증 판독이 읽은 사용내역은 **`basicsPending`인 거래에만** 반영된다.
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from domain.accounts.models import Role, Team, User
from domain.cards.models import Card, CardType
from domain.policies.models import RuleHit
from domain.settlements import draft_context, evidence_extract, submit_prep
from domain.settlements.attachments import Attachment, AttachmentKind, ExtractionStatus
from domain.settlements.models import (
    Category, Settlement, SettlementEvent, SettlementStatus as S,
)
from domain.transactions.models import Receipt, Transaction


class _Base(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="영업팀", bu="영업본부")
        self.user = User.objects.create_user("kim", password="pw", role=Role.EMPLOYEE,
                                             team=self.team, first_name="김영업")
        self.card = Card.objects.create(card_type=CardType.PERSONAL, owner=self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _settlement(self, *, basics_pending=False, **kwargs):
        tx = Transaction.objects.create(
            card=self.card, merchant="강남한식당", amount=Decimal("45000"), ts=timezone.now(),
            raw_payload={"source": "USER_UPLOAD",
                         evidence_extract.BASICS_PENDING_KEY: basics_pending},
        )
        Receipt.objects.create(matched_tx=tx, status="MATCHED", file_ref="r.jpg")
        defaults = dict(transaction=tx, submitted_by=self.user, team=self.team, status=S.DRAFT,
                        category=Category.MEAL, purpose="팀 점심")
        defaults.update(kwargs)
        return Settlement.objects.create(**defaults)


class DraftContextTests(_Base):
    # ① 미리보기는 감사 로그를 오염시키지 않는다
    def test_판정_미리보기가_rule_hits를_남기지_않는다(self):
        s = self._settlement()
        draft_context.build(s)
        self.assertEqual(RuleHit.objects.count(), 0)

    def test_판정_미리보기가_상태를_바꾸지_않는다(self):
        s = self._settlement()
        draft_context.build(s)
        s.refresh_from_db()
        self.assertEqual(s.status, S.DRAFT)

    # ② 사실이 한 묶음으로 온다
    def test_기본내역과_사실이_함께_온다(self):
        s = self._settlement()
        ctx = draft_context.build(s)
        self.assertEqual(ctx["basics"]["merchant"], "강남한식당")
        self.assertEqual(ctx["basics"]["amount"], 45000)
        self.assertIn("facts", ctx)
        self.assertIn("judgement", ctx)
        self.assertEqual(ctx["current"]["category"], Category.MEAL)

    def test_값이_없는_필드는_싣지_않는다(self):
        """46칸을 전부 실으면 대부분이 null이라 모델의 주의가 흩어진다."""
        s = self._settlement()
        ctx = draft_context.build(s)
        self.assertTrue(all(f["value"] not in (None, "") for f in ctx["facts"]))

    def test_사실에_설명이_붙는다(self):
        """경로만 주면 극성이 뒤집힌 필드를 반대로 읽는다(`expense_purpose_missing`)."""
        s = self._settlement()
        ctx = draft_context.build(s)
        self.assertTrue(any(f.get("desc") for f in ctx["facts"]))

    def test_첨부_추출_사실이_출처와_함께_온다(self):
        s = self._settlement()
        Attachment.objects.create(
            settlement=s, kind=AttachmentKind.PRE_APPROVAL, original_name="approval.png",
            extraction_status=ExtractionStatus.DONE,
            extracted={"approval.pre_approval_obtained": True},
            field_confidence={"approval.pre_approval_obtained": 0.9},
        )
        ctx = draft_context.build(s)
        att = ctx["attachments"][0]
        self.assertEqual(att["kind"], AttachmentKind.PRE_APPROVAL)
        self.assertEqual(att["facts"][0]["path"], "approval.pre_approval_obtained")
        self.assertEqual(att["facts"][0]["confidence"], 0.9)

    # ③ 보완요청 맥락
    def test_보완요청으로_돌아온_건은_사유가_온다(self):
        s = self._settlement(status=S.RETURNED)
        SettlementEvent.objects.create(
            settlement=s, from_state=S.IN_REVIEW, to_state=S.RETURNED,
            actor=self.user, reason="참석자 명단이 없습니다.",
        )
        ctx = draft_context.build(s)
        self.assertEqual(ctx["returnContext"]["reason"], "참석자 명단이 없습니다.")

    def test_돌아오지_않은_건은_보완_맥락이_없다(self):
        self.assertIsNone(draft_context.build(self._settlement())["returnContext"])

    # 내부 API
    def test_내부_API가_묶음을_그대로_내려준다(self):
        s = self._settlement()
        r = APIClient().get(f"/api/internal/settlement-draft-context/{s.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["settlementId"], s.id)
        self.assertIn("judgement", r.data)


class SubmitPrepTests(_Base):
    """④ 「멈춰 세울지」는 서버가 정한다."""

    def _prep(self, s, polish_result):
        with patch.object(submit_prep, "_polish", return_value=polish_result):
            return submit_prep.prepare(s)

    def _polished(self, original, polished, applied=True, review=None):
        return {"applied": applied, "original": original, "polished": polished,
                "review": review or [], "diff": {}, "modelReported": {}}

    def test_다듬은_문장이_저장된다(self):
        s = self._settlement(purpose="회식함")
        self._prep(s, self._polished("회식함", "팀 회식 목적으로 사용했습니다."))
        s.refresh_from_db()
        self.assertEqual(s.purpose, "팀 회식 목적으로 사용했습니다.")

    def test_과하게_바뀐_문장은_적용하지_않는다(self):
        """`applied=False`면 원문이 그대로 남고, 화면이 두 문장을 나란히 띄운다."""
        s = self._settlement(purpose="회식함")
        prep = self._prep(s, self._polished(
            "회식함", "팀원 8명과 회식했습니다.", applied=False,
            review=[{"level": "warn", "code": "PURPOSE_OVER_REWRITTEN", "text": "..."}],
        ))
        s.refresh_from_db()
        self.assertEqual(s.purpose, "회식함")
        self.assertTrue(prep["shouldConfirm"])

    def test_REVIEW로는_멈추지_않는다(self):
        """룰이 자동 판단하지 않고 회계가 보는 것뿐이라 지출자가 고칠 것이 없다."""
        notices = submit_prep._judgement_notices(
            {"available": True, "decision": "REVIEW", "flags": [{"code": "X", "label": "x"}]}
        )
        self.assertEqual(notices, [])

    def test_PASS면_안내가_없다(self):
        self.assertEqual(submit_prep._judgement_notices({"available": True, "decision": "PASS"}), [])

    def test_RETURN이면_사유와_함께_멈춘다(self):
        notices = submit_prep._judgement_notices({
            "available": True, "decision": "RETURN",
            "flags": [{"code": "EVIDENCE_MISSING", "label": "적격증빙 없음",
                       "description": "영수증이 없습니다.", "ownerLabel": "지출자"}],
        })
        self.assertEqual(notices[0]["level"], "blocker")
        self.assertTrue(any(n["code"] == "EVIDENCE_MISSING" for n in notices))

    def test_미리보기를_못_얻어도_제출을_막지_않는다(self):
        """다만 「확인했다」고도 하지 않는다 — info로 사실을 남긴다."""
        notices = submit_prep._judgement_notices({"available": False, "error": "boom"})
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]["level"], "info")

    def test_ai가_죽어도_제출_준비가_끝난다(self):
        """다듬기는 편의 기능이다 — 실패해도 원문 그대로 두고 진행한다."""
        s = self._settlement(purpose="팀 점심")
        prep = self._prep(s, self._polished("팀 점심", "팀 점심", applied=False))
        s.refresh_from_db()
        self.assertEqual(s.purpose, "팀 점심")
        self.assertIn("notices", prep)


class ReceiptBasicsTests(_Base):
    """⑤ 영수증이 읽은 사용내역은 「비어 있는 자리에만」."""

    def _attachment(self, s):
        return Attachment.objects.create(
            settlement=s, kind=AttachmentKind.RECEIPT, original_name="r.png", file_ref="r.png",
        )

    def _read(self):
        return {"merchant": "스타벅스 역삼점", "amount": 8200, "date": "2026-08-19", "time": "09:12"}

    def test_기본내역_대기_건은_판독값으로_채워진다(self):
        s = self._settlement(basics_pending=True)
        s.transaction.merchant = evidence_extract.PLACEHOLDER_MERCHANT
        s.transaction.amount = Decimal("0")
        s.transaction.save()
        applied = evidence_extract._apply_receipt_basics(self._attachment(s), self._read())
        s.transaction.refresh_from_db()
        self.assertEqual(s.transaction.merchant, "스타벅스 역삼점")
        self.assertEqual(int(s.transaction.amount), 8200)
        self.assertIn("가맹점", applied)

    def test_ERP_원장_건은_덮지_않는다(self):
        """부분취소·팁으로 금액이 다를 수 있고, 그때 맞는 쪽은 카드사 원장이다."""
        s = self._settlement(basics_pending=False)
        evidence_extract._apply_receipt_basics(self._attachment(s), self._read())
        s.transaction.refresh_from_db()
        self.assertEqual(s.transaction.merchant, "강남한식당")
        self.assertEqual(int(s.transaction.amount), 45000)

    def test_사람이_친_값은_덮지_않는다(self):
        """플레이스홀더·0일 때만 채운다 — 사용자가 보는 앞에서 값이 바뀌면 안 된다."""
        s = self._settlement(basics_pending=True)
        evidence_extract._apply_receipt_basics(self._attachment(s), self._read())
        s.transaction.refresh_from_db()
        self.assertEqual(s.transaction.merchant, "강남한식당")
        self.assertEqual(int(s.transaction.amount), 45000)

    def test_다_채우면_대기_표시가_내려간다(self):
        s = self._settlement(basics_pending=True)
        s.transaction.merchant = evidence_extract.PLACEHOLDER_MERCHANT
        s.transaction.amount = Decimal("0")
        s.transaction.save()
        evidence_extract._apply_receipt_basics(self._attachment(s), self._read())
        s.transaction.refresh_from_db()
        self.assertFalse(s.transaction.raw_payload[evidence_extract.BASICS_PENDING_KEY])

    def test_읽지_못한_항목은_빈_값으로_덮지_않는다(self):
        s = self._settlement(basics_pending=True)
        s.transaction.merchant = evidence_extract.PLACEHOLDER_MERCHANT
        s.transaction.save()
        evidence_extract._apply_receipt_basics(self._attachment(s), {"merchant": "", "amount": None})
        s.transaction.refresh_from_db()
        self.assertEqual(s.transaction.merchant, evidence_extract.PLACEHOLDER_MERCHANT)
