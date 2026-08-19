"""가맹점 업종 캐시 내부 API 테스트 (§7-1)."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import industry
from .models import MerchantCategory, MerchantSource


class MerchantCategoryLookupTests(TestCase):
    def test_miss_returns_hit_false(self):
        resp = self.client.get(reverse("internal_merchant_category_lookup", args=["존재안함"]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"hit": False})

    def test_hit_returns_cached_value(self):
        MerchantCategory.objects.create(
            normalized_name="스타벅스", industry_code="CAFE", industry_label="카페",
            source=MerchantSource.KAKAO, confidence=0.8,
        )
        resp = self.client.get(reverse("internal_merchant_category_lookup", args=["스타벅스"]))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["hit"])
        self.assertEqual(body["industry_code"], "CAFE")
        self.assertEqual(body["industry_label"], "카페")
        self.assertEqual(body["source"], "KAKAO")

    def test_expired_cache_is_treated_as_miss(self):
        row = MerchantCategory.objects.create(
            normalized_name="옛날가게", industry_code="RESTAURANT", industry_label="일반음식점",
            source=MerchantSource.KAKAO, confidence=0.8,
        )
        # auto_now 필드는 save()로 갱신되므로 update()로 우회해 31일 전 값을 강제한다.
        MerchantCategory.objects.filter(pk=row.pk).update(resolved_at=timezone.now() - timedelta(days=31))
        resp = self.client.get(reverse("internal_merchant_category_lookup", args=["옛날가게"]))
        self.assertEqual(resp.json(), {"hit": False})


class MerchantCategoryUpsertTests(TestCase):
    def test_requires_authentication(self):
        resp = self.client.post(
            reverse("internal_merchant_category_upsert"),
            data={"normalized_name": "무단가게", "industry_code": "OTHER", "industry_label": "기타"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_upsert_then_lookup_round_trip(self):
        from domain.accounts.models import Role, User

        # ACCOUNTANT_LEAD는 기본 능력에 RULE_VIEW가 포함된다(ROLE_DEFAULT_CAPABILITIES) —
        # ai 서비스 계정과 같은 capability 경로를 탄다.
        user = User.objects.create_user(username="svc-test", password="pw", role=Role.ACCOUNTANT_LEAD)
        self.client.force_login(user)

        resp = self.client.post(
            reverse("internal_merchant_category_upsert"),
            data={
                "normalized_name": "새가게", "industry_code": "CAFE", "industry_label": "카페",
                "source": "KAKAO", "confidence": 0.8, "raw": {"place_name": "새가게"},
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

        lookup = self.client.get(reverse("internal_merchant_category_lookup", args=["새가게"]))
        body = lookup.json()
        self.assertTrue(body["hit"])
        self.assertEqual(body["industry_label"], "카페")


class IndustryVocabularyTests(TestCase):
    """정본 업종 어휘(`industry.resolve`) — 판정 사실이 되는 값이라 접힘 규칙이 계약이다."""

    def test_canonical_label_and_code_pass_through(self):
        self.assertEqual(industry.resolve("주점/유흥"), ("BAR_ENTERTAINMENT", "주점/유흥"))
        self.assertEqual(industry.resolve("BAR_ENTERTAINMENT"), ("BAR_ENTERTAINMENT", "주점/유흥"))

    def test_regulation_wording_folds_into_canonical(self):
        """규정 원문 표기(제9조② 금지업종)가 룰이 비교하는 라벨로 접혀야 한다."""
        for raw in ("유흥주점", "단란주점", "유흥업소"):
            self.assertEqual(industry.canonical_label(raw), "주점/유흥", raw)
        self.assertEqual(industry.canonical_label("노래방"), "노래연습장")
        self.assertEqual(industry.canonical_label("카지노"), "사행성업종")
        for raw in ("이용업", "미용업"):
            self.assertEqual(industry.canonical_label(raw), "이·미용", raw)

    def test_legacy_seed_and_erp_wording_folds(self):
        """시드·ERP 수집이 쓰던 자유 표기 — 이 값들이 그대로 판정에 올라가고 있었다."""
        self.assertEqual(industry.canonical_label("한식"), "일반음식점")
        self.assertEqual(industry.canonical_label("분식"), "일반음식점")
        self.assertEqual(industry.canonical_label("서점"), "문구/사무용품")
        self.assertEqual(industry.canonical_label("종합소매"), "마트/편의점")
        self.assertEqual(industry.canonical_label("여객운송"), "주유/교통")

    def test_partial_match_prefers_longer_alias(self):
        """"유흥주점"이 "주점"보다 먼저 걸려야 같은 곳으로 접힌다(둘 다 BAR지만 순서는 계약)."""
        self.assertEqual(industry.canonical_label("강남 유흥주점 1호"), "주점/유흥")
        self.assertEqual(industry.canonical_label("강남한식당"), "일반음식점")

    def test_unknown_stays_unresolved_not_other(self):
        """모르는 값을 `기타`로 밀면 금지업종 별표가 `"*"→False`로 폴백해 안전하다고 단정한다."""
        self.assertEqual(industry.resolve("부동산중개"), ("", ""))
        self.assertEqual(industry.resolve(""), ("", ""))
        self.assertEqual(industry.resolve(None), ("", ""))


class MerchantCategoryVocabularyGateTests(TestCase):
    """캐시 쓰기 경로는 정본 어휘만 받는다 — ai 미러가 어긋나면 여기서 드러나야 한다."""

    def _login(self):
        from domain.accounts.models import Role, User

        user = User.objects.create_user(username="svc-vocab", password="pw", role=Role.ACCOUNTANT_LEAD)
        self.client.force_login(user)

    def test_non_canonical_industry_is_rejected(self):
        self._login()
        resp = self.client.post(
            reverse("internal_merchant_category_upsert"),
            data={"normalized_name": "이상한가게", "industry_code": "FD6", "industry_label": "음식점업(카카오)"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(MerchantCategory.objects.filter(normalized_name="이상한가게").exists())

    def test_label_only_payload_is_folded_to_code(self):
        self._login()
        resp = self.client.post(
            reverse("internal_merchant_category_upsert"),
            data={"normalized_name": "포차집", "industry_label": "주점/유흥"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        row = MerchantCategory.objects.get(normalized_name="포차집")
        self.assertEqual((row.industry_code, row.industry_label), ("BAR_ENTERTAINMENT", "주점/유흥"))
