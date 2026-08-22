"""비용분류 어휘 정합 회귀 — 「목록의 정본은 서버 하나」.

## 왜 이 파일이 생겼나

같은 6개 목록이 저장소 안 9곳에 상수로 복사돼 있었고(ai Literal 2곳·프론트 5곳·core
폴백 2곳), 서버는 정작 저장되는 값을 **검증하지 않았다** — `choices=`는 DB 제약이 아니고
커스텀 create/update는 `full_clean()`을 부르지 않는다. 화면 드롭다운만이 유일한 방어였다.

고정하는 계약:
  ① 어휘를 내려주는 자리는 `/api/meta/categories/` 하나다(화면·ai가 같은 목록을 본다).
  ② 목록 밖 값은 **저장되지 않는다**(create·PATCH 모두 400).
  ③ `""`(미기재)는 유효한 상태다 — 「아직 못 정했다」이고 판정이 `CATEGORY_MISSING`으로
     잡아 검토로 보낸다. `기타`("어디에도 안 맞는다"는 확정)와 다르다.
  ④ AI가 분류를 특정하지 못하면 **비워 둔다** — 실재 과목(옛 `비품`)으로 밀지 않는다.
"""
from decimal import Decimal
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from domain.accounts.models import Role, Team, User
from domain.cards.models import Card, CardType
from domain.policies.models import RuleGraph
from domain.policies.scope import normalize_scope
from domain.settlements import draft_agent, evidence_extract
from domain.settlements.models import Category, Settlement, SettlementStatus as S
from domain.transactions.models import Receipt, Transaction


class CategoryMetaEndpointTests(TestCase):
    """① 어휘를 내려주는 자리는 하나."""

    def test_어휘_응답이_정본과_일치한다(self):
        r = self.client.get("/api/meta/categories/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([row["value"] for row in r.data["categories"]], list(Category.values))
        self.assertEqual([row["label"] for row in r.data["categories"]], list(Category.labels))

    def test_룰_scope는_GLOBAL과_분류의_합집합이다(self):
        """조합 규칙(GLOBAL ∪ Category)도 서버가 정한다 — 클라이언트가 이어붙이지 않는다."""
        r = self.client.get("/api/meta/categories/")
        self.assertEqual(r.data["ruleScopes"], ["GLOBAL", *Category.values])

    def test_로그인_없이도_읽힌다(self):
        """사용자 데이터가 아니라 어휘다 — 로그인 화면 이전에도 필요하다."""
        self.assertEqual(APIClient().get("/api/meta/categories/").status_code, 200)


class CategoryValidationTests(TestCase):
    """② 목록 밖 값은 저장되지 않는다."""

    def setUp(self):
        self.team = Team.objects.create(name="영업팀", bu="영업본부")
        self.user = User.objects.create_user("kim", password="pw", role=Role.EMPLOYEE,
                                             team=self.team, first_name="김영업")
        self.card = Card.objects.create(card_type=CardType.PERSONAL, owner=self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _settlement(self, **kwargs):
        tx = Transaction.objects.create(card=self.card, merchant="스타벅스 역삼점",
                                        amount=Decimal("8000"), ts=timezone.now())
        Receipt.objects.create(matched_tx=tx, status="MATCHED", file_ref="r.jpg")
        defaults = dict(transaction=tx, submitted_by=self.user, team=self.team,
                        status=S.DRAFT, category="", ai_category=Category.MEAL)
        defaults.update(kwargs)
        return Settlement.objects.create(**defaults)

    def test_모르는_분류로_수정하면_400(self):
        s = self._settlement()
        r = self.client.patch(f"/api/settlements/{s.id}/", {"category": "업무활성"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("업무활성", r.data["detail"])
        s.refresh_from_db()
        self.assertEqual(s.category, "")     # 저장되지 않았다

    def test_기타는_정상_저장된다(self):
        """유연성 장치 — 6개 어디에도 안 맞는 지출을 사람이 확정할 자리."""
        s = self._settlement()
        r = self.client.patch(f"/api/settlements/{s.id}/", {"category": Category.OTHER}, format="json")
        self.assertEqual(r.status_code, 200)
        s.refresh_from_db()
        self.assertEqual(s.category, Category.OTHER)

    # ③ 미기재는 유효한 상태 — 「기타」와 다르다
    def test_빈_분류는_확정값을_지우지_않는다(self):
        s = self._settlement(category=Category.MEAL)
        self.client.patch(f"/api/settlements/{s.id}/", {"category": ""}, format="json")
        s.refresh_from_db()
        self.assertEqual(s.category, Category.MEAL)

    def test_기타와_미기재는_다른_값이다(self):
        """`기타`로 밀면 「분류 미기재」 게이트가 안 걸려 확인 안 한 건이 통과한다."""
        self.assertNotEqual(Category.OTHER.value, "")
        self.assertIn(Category.OTHER.value, Category.values)


class DraftFallbackTests(TestCase):
    """④ AI가 못 정하면 비워 둔다(실재 과목으로 밀지 않는다)."""

    def test_분류를_특정하지_못하면_빈_값(self):
        category, confidence, reason = draft_agent._guess_category("알수없는가맹점ZZZ", "")
        self.assertEqual(category, "")
        self.assertEqual(confidence, 0.0)
        self.assertIn("특정하지 못했습니다", reason)

    def test_캐치올이_비품으로_흘러가지_않는다(self):
        """우체국·택배·인쇄는 비품이 아니라 `기타`다 — 비품은 자기 예산·scope 그래프가 있다."""
        category, _, _ = draft_agent._guess_category("우체국 역삼", "")
        self.assertEqual(category, Category.OTHER)

    def test_초안이_빈_분류로_나가도_터지지_않는다(self):
        """빈 분류면 규정 힌트 조회 자체가 성립하지 않는다 — 조회하지 않고 빈 목록."""
        draft = draft_agent.suggest_draft({"merchant": "알수없는가맹점ZZZ", "amount": 50000})
        self.assertEqual(draft["draft"]["category"], "")
        self.assertEqual(draft["policyHints"], [])


class RuleScopeTests(TestCase):
    """분류가 늘면 룰 그래프 scope도 함께 늘어난다(CHECK 제약 포함)."""

    def test_기타_scope_그래프를_만들_수_있다(self):
        graph = RuleGraph.objects.create(name="기타 지출 룰", scope=Category.OTHER, version=1)
        self.assertEqual(graph.scope, Category.OTHER)

    def test_정규화가_기타를_그대로_통과시킨다(self):
        self.assertEqual(normalize_scope(Category.OTHER.value), Category.OTHER.value)


class CreateCategoryValidationTests(TestCase):
    """② create 경로도 같은 검증을 거친다 — 한쪽만 막으면 다른 쪽으로 들어온다."""

    def setUp(self):
        self.team = Team.objects.create(name="영업팀", bu="영업본부")
        self.user = User.objects.create_user("kim", password="pw", role=Role.EMPLOYEE,
                                             team=self.team, first_name="김영업")
        self.card = Card.objects.create(card_type=CardType.PERSONAL, owner=self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _payload(self, **over):
        base = {"merchant": "강남한식당", "amount": "45000", "date": "2026-08-20",
                "cardId": self.card.id, "category": Category.MEAL, "purpose": "팀 점심",
                "receipt": SimpleUploadedFile("r.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64,
                                              content_type="image/png")}
        base.update(over)
        return base

    def test_모르는_분류로는_등록되지_않는다(self):
        r = self.client.post("/api/settlements/", self._payload(category="숙박비"), format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Settlement.objects.exists())

    def test_AI_제안이_목록_밖이어도_막는다(self):
        """`aiCategory`도 검증한다 — 확정값이 비면 이 값이 그대로 `category`가 된다."""
        r = self.client.post("/api/settlements/",
                             self._payload(category="", aiCategory="업무활성"), format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_분류를_비운_채로도_등록된다(self):
        """「선택 필요」 상태로 저장하고 판정이 `CATEGORY_MISSING`으로 잡는 흐름."""
        with patch.object(evidence_extract, "schedule"):
            r = self.client.post("/api/settlements/", self._payload(category=""), format="multipart")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Settlement.objects.get().category, "")
