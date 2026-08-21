"""보완요청·반려 **사유 초안** 회귀.

고정하는 계약:
  ① 사유 선택지는 **서버가 정본**이다 — 화면 칩과 LLM 출력 enum이 같은 목록을 봐야 한다.
  ② LLM이 목록 밖 값을 만들면 **버린다** — 칩과 어긋난 문자열이 저장되면 집계가 갈린다.
  ③ ai가 없어도 **빈손으로 두지 않는다** — 판정 플래그의 설명을 이어 폴백 문장을 만든다.
     지어내는 게 아니라 이미 확정된 사유 코드를 펴는 것이라 사실과 어긋나지 않는다.
  ④ 초안 생성 실패가 **결정을 막지 않는다**(예외를 올리지 않는다).
  ⑤ LLM에 넘기는 건 판정이 실제로 남긴 것뿐 — 코드만이 아니라 라벨·설명까지 펴서 준다
     (코드만 주면 모델이 제 나름대로 해석해 없는 규정을 지어낸다).
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from domain.accounts.models import Role, Team, User
from domain.cards.models import Card, CardType
from domain.policies.flags import seed_rule_flags
from domain.settlements import decision_reasons
from domain.settlements.models import Category, Settlement, SettlementStatus as S
from domain.transactions.models import Transaction


class DecisionReasonTests(TestCase):
    def setUp(self):
        seed_rule_flags()
        self.team = Team.objects.create(name="영업팀", bu="영업본부")
        self.user = User.objects.create_user("kim", password="pw", role=Role.EMPLOYEE,
                                             team=self.team, first_name="김영업")
        card = Card.objects.create(card_type=CardType.PERSONAL, owner=self.user)
        tx = Transaction.objects.create(card=card, merchant="강남한식당",
                                        amount=Decimal("450000"), ts=timezone.now())
        self.settlement = Settlement.objects.create(
            transaction=tx, submitted_by=self.user, team=self.team, status=S.TEAM_COLLECTING,
            category=Category.ENTERTAIN, purpose="", merchant_industry="일반음식점",
            # `rule_decision`/`rule_flags`는 `rule_judgement` JSON의 읽기 전용 파생이다.
            rule_judgement={"decision": "REVIEW", "flags": ["EVIDENCE_MISSING", "PURPOSE_UNCLEAR"]},
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = f"/api/settlements/{self.settlement.id}/decision-reason/"

    # ⑤ 넘기는 사실
    def test_판정_사유를_라벨과_설명까지_펴서_넘긴다(self):
        ctx = decision_reasons.build_context(self.settlement, "RETURN")
        codes = [f["code"] for f in ctx["judgement"]["flags"]]
        self.assertEqual(codes, ["EVIDENCE_MISSING", "PURPOSE_UNCLEAR"])
        first = ctx["judgement"]["flags"][0]
        self.assertEqual(first["label"], "적격증빙 없음")
        self.assertTrue(first["description"])       # 코드만 주면 모델이 규정을 지어낸다
        self.assertEqual(ctx["settlement"]["amount"], 450000)
        self.assertEqual(ctx["options"], decision_reasons.RETURN_REASONS)

    # ① 선택지는 서버가 정본
    def test_처리_구분에_따라_선택지가_갈린다(self):
        self.assertEqual(decision_reasons.options("RETURN"), decision_reasons.RETURN_REASONS)
        self.assertEqual(decision_reasons.options("REJECT"), decision_reasons.REJECT_REASONS)
        self.assertNotEqual(decision_reasons.RETURN_REASONS, decision_reasons.REJECT_REASONS)

    def test_응답이_선택지를_함께_싣는다(self):
        with patch("domain.settlements.decision_reasons.httpx.post", side_effect=RuntimeError("ai down")):
            body = self.client.post(self.url, {"decision": "RETURN"}, format="json").json()
        self.assertEqual(body["options"], decision_reasons.RETURN_REASONS)

    # ② 목록 밖 값은 버린다
    def test_LLM이_목록_밖_사유를_만들면_버린다(self):
        with patch("domain.settlements.decision_reasons.httpx.post") as post:
            post.return_value.json.return_value = {"reason": "내 맘대로 사유", "detail": "본문"}
            post.return_value.raise_for_status.return_value = None
            body = self.client.post(self.url, {"decision": "RETURN"}, format="json").json()
        self.assertIn(body["reason"], decision_reasons.RETURN_REASONS)
        self.assertEqual(body["detail"], "본문")     # 본문은 살린다(사유 코드만 정규화)

    def test_LLM_사유가_목록_안이면_그대로_쓴다(self):
        with patch("domain.settlements.decision_reasons.httpx.post") as post:
            post.return_value.json.return_value = {"reason": "증빙 누락", "detail": "영수증을 첨부해 주세요."}
            post.return_value.raise_for_status.return_value = None
            body = self.client.post(self.url, {"decision": "RETURN"}, format="json").json()
        self.assertEqual(body["reason"], "증빙 누락")
        self.assertEqual(body["source"], "ai")

    # ③④ ai 없이도 초안이 나온다
    def test_ai가_없으면_판정_플래그로_초안을_만든다(self):
        with patch("domain.settlements.decision_reasons.httpx.post", side_effect=RuntimeError("ai down")):
            body = self.client.post(self.url, {"decision": "RETURN"}, format="json").json()
        self.assertEqual(body["source"], "fallback")
        self.assertEqual(body["reason"], "증빙 누락")          # EVIDENCE_MISSING → 매핑
        self.assertIn("적격증빙", body["detail"])              # 플래그 설명을 그대로 이어붙인다
        self.assertIn("다시 제출", body["detail"])             # 보완요청은 무엇을 하면 되는지 안내

    def test_판정_사유가_없으면_본문을_지어내지_않는다(self):
        self.settlement.rule_judgement = {"decision": "REVIEW", "flags": []}
        self.settlement.save(update_fields=["rule_judgement"])
        with patch("domain.settlements.decision_reasons.httpx.post", side_effect=RuntimeError("x")):
            body = self.client.post(self.url, {"decision": "RETURN"}, format="json").json()
        self.assertEqual(body["detail"], "")
        self.assertEqual(body["reason"], "기타")

    def test_반려는_반려_선택지에서_고른다(self):
        self.settlement.rule_judgement = {"decision": "REVIEW", "flags": ["PROHIBITED_MERCHANT"]}
        self.settlement.save(update_fields=["rule_judgement"])
        with patch("domain.settlements.decision_reasons.httpx.post", side_effect=RuntimeError("x")):
            body = self.client.post(self.url, {"decision": "REJECT"}, format="json").json()
        self.assertEqual(body["reason"], "명백한 규정 위반")
        self.assertIn(body["reason"], decision_reasons.REJECT_REASONS)
        # 반려는 최종이라 재제출을 안내하지 않는다.
        self.assertNotIn("다시 제출", body["detail"])

    def test_잘못된_decision은_400(self):
        r = self.client.post(self.url, {"decision": "APPROVE"}, format="json")
        self.assertEqual(r.status_code, 400)
