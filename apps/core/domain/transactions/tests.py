"""가맹점 업종 캐시 내부 API 테스트 (§7-1)."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

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
