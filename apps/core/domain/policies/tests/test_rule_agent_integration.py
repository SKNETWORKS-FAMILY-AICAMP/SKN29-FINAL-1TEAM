"""Rule Agent(생성) ↔ Django 통합 경로 회귀 테스트.

여기서 지키는 건 세 가지다 — 셋 다 실제로 통합을 막았던 것들이다:

  ① **인가**: 룰 콘솔 쓰기 API는 capability `rule_view` 없이는 못 쓴다. Rule Agent는
     사람 세션이 없어 403을 받았고(구 G-16), 이제 전용 서비스 계정으로 통과한다.
  ② **scope**: Agent가 보내는 과목명이 `Category` 값으로 접혀야 한다. 접히지 않으면
     `create_graph_draft`가 400을 내며 인증을 풀어도 저장이 안 됐다.
  ③ **생성 이력**: 그래프 단위 `generation_meta`가 저장되고, 다음 버전으로는
     **복제되지 않는다**(사람이 손댄 버전을 AI 생성물로 오인하지 않도록).
"""
from django.test import TestCase
from rest_framework.test import APIClient

from domain.accounts.models import Capability, Role, User
from domain.common.management.commands.ensure_service_account import (
    SERVICE_USERNAME,
    ensure_service_account,
)
from domain.policies.models import RuleGraph, RuleGraphStatus
from domain.policies.services import create_draft_version, create_graph_draft


class ServiceAccountTests(TestCase):
    def test_account_has_only_rule_view(self):
        user, created, _ = ensure_service_account(password="pw")
        self.assertTrue(created)
        self.assertEqual(user.username, SERVICE_USERNAME)
        # 최소 권한 — 회계 검토·룰 활성까지 딸려오면 Agent가 승인까지 할 수 있게 된다.
        self.assertEqual(user.capabilities, [Capability.RULE_VIEW.value])
        self.assertTrue(user.has_capability(Capability.RULE_VIEW))
        self.assertFalse(user.has_capability(Capability.RULE_ACTIVATE))

    def test_rerun_is_idempotent_and_resets_widened_capabilities(self):
        user, _, _ = ensure_service_account(password="pw")
        user.extra_capabilities = [Capability.RULE_ACTIVATE.value]
        user.save(update_fields=["extra_capabilities"])

        again, created, _ = ensure_service_account(password="pw")
        self.assertFalse(created)
        self.assertEqual(again.pk, user.pk)
        self.assertEqual(again.capabilities, [Capability.RULE_VIEW.value])


class RuleGraphWriteAuthorizationTests(TestCase):
    """`POST /api/rules/drafts/` — 서비스 계정이 실제로 통과하는지."""

    def setUp(self):
        self.client = APIClient()

    def test_anonymous_is_rejected(self):
        resp = self.client.post("/api/rules/drafts/", {"name": "x", "scope": "접대"}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_user_without_rule_view_is_rejected(self):
        User.objects.create_user("nobody", password="pw", role=Role.EMPLOYEE)
        self.client.login(username="nobody", password="pw")
        resp = self.client.post("/api/rules/drafts/", {"name": "x", "scope": "접대"}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_service_account_can_create_draft(self):
        ensure_service_account(password="pw")
        self.client.login(username=SERVICE_USERNAME, password="pw")
        resp = self.client.post(
            "/api/rules/drafts/", {"name": "접대 자동생성 초안", "scope": "접대"}, format="json"
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["status"], RuleGraphStatus.DRAFT)


class ScopeNormalizationTests(TestCase):
    """Agent는 규정 문서 표기(기업업무추진비·회식)를 그대로 보낼 수 있어야 한다."""

    def setUp(self):
        ensure_service_account(password="pw")
        self.client = APIClient()
        self.client.login(username=SERVICE_USERNAME, password="pw")

    def _create(self, scope):
        return self.client.post(
            "/api/rules/drafts/", {"name": f"{scope} 초안", "scope": scope}, format="json"
        )

    def test_regulation_subject_is_folded_into_category(self):
        resp = self._create("기업업무추진비")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["scope"], "접대")

    def test_hoesik_lands_on_own_scope(self):
        # [2026-08-14] 회식은 더 이상 식대 그래프에 얹혀가는 별칭이 아니다 — Category.GATHERING("회식")로
        # 독립 승격됐고, 자기 자신을 가리키는 scope로 원문 그대로 통과한다(scope.py가 SoT).
        resp = self._create("회식")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["scope"], "회식")

    def test_global_gate_scope_is_preserved(self):
        resp = self._create("GLOBAL")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["scope"], "GLOBAL")

    def test_unknown_scope_is_rejected_with_reason(self):
        resp = self._create("존재하지않는과목")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("scope", resp.data["detail"])


class GenerationMetaTests(TestCase):
    def test_meta_is_saved_and_exposed(self):
        meta = {"agent": "rule-agent-v0", "model": "gpt-4o-mini", "sources": [{"citation": "「업무추진비_사용규정」 제6조"}]}
        graph = create_graph_draft("접대 초안", "접대", generation_meta=meta)
        graph.refresh_from_db()
        self.assertEqual(graph.generation_meta["agent"], "rule-agent-v0")

        ensure_service_account(password="pw")
        client = APIClient()
        client.login(username=SERVICE_USERNAME, password="pw")
        resp = client.get(f"/api/rules/{graph.pk}/")
        self.assertEqual(resp.data["generationMeta"]["model"], "gpt-4o-mini")

    def test_human_created_graph_has_empty_meta(self):
        graph = create_graph_draft("사람이 만든 초안", "식대")
        self.assertEqual(graph.generation_meta, {})

    def test_next_version_does_not_inherit_meta(self):
        """생성 이력은 그 버전의 것이다 — 사람이 손댄 다음 버전까지 AI 생성물로 찍히면 안 된다."""
        graph = create_graph_draft("접대 초안", "접대", generation_meta={"agent": "rule-agent-v0"})
        RuleGraph.objects.filter(pk=graph.pk).update(status=RuleGraphStatus.ACTIVE)
        graph.refresh_from_db()

        nxt = create_draft_version(graph)
        self.assertEqual(nxt.generation_meta, {})
        self.assertEqual(nxt.family_key, graph.family_key)
