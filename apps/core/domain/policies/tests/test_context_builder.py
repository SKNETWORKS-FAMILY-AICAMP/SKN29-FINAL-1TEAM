"""조립기(별표 선해소) 테스트 — `_context/policy-domain.md` §2·§3."""
from datetime import date

from django.test import TestCase
from django.utils import timezone

from domain.policies.context_builder import (
    RESOLVERS, build_rule_context, load_tables, lookup, resolve_policy,
)
from domain.policies.engine import run_rule_engine
from domain.policies.eval_context import EVAL_CONTEXT_SCHEMA_PATHS, empty_eval_context
from domain.policies.models import PolicyTable
from domain.policies.tiger_tables import DEMO_POLICY, upsert_all


class LookupTests(TestCase):
    def test_two_axis_table(self):
        table = PolicyTable(
            key="lodging_limit_table",
            key_axes=["trip.trip_type", "trip.region_grade"],
            payload={"국내": {"A": 120_000, "B": 90_000}, "해외": {"A": 250_000}},
            effective_date=date(2026, 1, 1),
        )
        ctx = empty_eval_context()
        ctx["trip"].update({"trip_type": "국내", "region_grade": "B"})
        self.assertEqual(lookup(table, ctx), 90_000)

        ctx["trip"].update({"trip_type": "해외", "region_grade": "A"})
        self.assertEqual(lookup(table, ctx), 250_000)

    def test_axis_can_grow_without_code_change(self):
        """축이 2개 → 3개로 늘어도 조립기 코드는 그대로다(마이그레이션 0)."""
        table = PolicyTable(
            key="lodging_limit_table",
            key_axes=["trip.trip_type", "trip.region_grade", "user.position"],
            payload={"국내": {"A": {"*": 120_000, "본부장": 200_000}}},
            effective_date=date(2026, 1, 1),
        )
        ctx = empty_eval_context()
        ctx["trip"].update({"trip_type": "국내", "region_grade": "A"})
        ctx["user"]["position"] = "본부장"
        self.assertEqual(lookup(table, ctx), 200_000)

    def test_wildcard_fallback_when_key_missing(self):
        """키가 SoR에 없어도(예: user.position 미구현) 와일드카드로 해소된다."""
        table = PolicyTable(
            key="daily_limit_table", key_axes=["user.position"],
            payload={"*": 600_000, "과장": 300_000}, effective_date=date(2026, 1, 1),
        )
        ctx = empty_eval_context()
        self.assertEqual(lookup(table, ctx), 600_000)
        ctx["user"]["position"] = "과장"
        self.assertEqual(lookup(table, ctx), 300_000)

    def test_axisless_and_list_leaf(self):
        scalar = PolicyTable(key="settlement_deadline_table", key_axes=[],
                             payload={"value": 7}, effective_date=date(2026, 1, 1))
        self.assertEqual(lookup(scalar, empty_eval_context()), 7)

        listed = PolicyTable(key="required_evidence_table", key_axes=["category.value"],
                             payload={"*": ["영수증"]}, effective_date=date(2026, 1, 1))
        self.assertEqual(lookup(listed, empty_eval_context()), ["영수증"])


class EffectiveDateTests(TestCase):
    def setUp(self):
        common = {"key": "evidence_threshold_table", "key_axes": []}
        PolicyTable.objects.create(**common, payload={"value": 30_000},
                                   effective_date=date(2026, 1, 1), superseded_date=date(2026, 9, 1))
        PolicyTable.objects.create(**common, payload={"value": 50_000},
                                   effective_date=date(2026, 9, 1))

    def test_picks_table_valid_at_expense_date(self):
        """개정은 INSERT다 — 과거 판정은 그 시점 한도로 재현된다."""
        before = load_tables(date(2026, 8, 10))["evidence_threshold_table"]
        after = load_tables(date(2026, 9, 15))["evidence_threshold_table"]
        self.assertEqual(lookup(before, empty_eval_context()), 30_000)
        self.assertEqual(lookup(after, empty_eval_context()), 50_000)


class SeededTablesTests(TestCase):
    def setUp(self):
        upsert_all()

    def test_every_resolver_target_is_in_the_schema_catalog(self):
        """조립기가 채우는 필드는 전부 EvalContext 카탈로그에 있어야 한다."""
        for field in RESOLVERS:
            self.assertIn(f"policy.{field}", EVAL_CONTEXT_SCHEMA_PATHS)

    def test_seeded_tables_resolve_every_policy_field(self):
        """시드 별표만으로 policy.* 전 종이 해소된다 → 미해소 플래그 0."""
        ctx = empty_eval_context()
        unresolved = resolve_policy(ctx, load_tables())
        self.assertEqual(unresolved, [])
        self.assertEqual(len(ctx["policy"]), len(RESOLVERS))
        self.assertTrue(all(value is not None for value in ctx["policy"].values()))

    def test_resolved_values_match_demo_snapshot(self):
        """시연 EvalContext(DEMO_POLICY)와 조립기 결과가 어긋나지 않는다."""
        ctx = empty_eval_context()
        resolve_policy(ctx, load_tables())
        for field, expected in DEMO_POLICY.items():
            self.assertEqual(ctx["policy"][field], expected, field)

    def test_original_table_is_kept_for_audit(self):
        """tables는 고정 목록이 아니라 조립기가 실제 사용한 별표만 동적으로 담는다."""
        ctx = empty_eval_context()
        self.assertEqual(ctx["tables"], {})
        resolve_policy(ctx, load_tables())
        self.assertEqual(ctx["tables"]["lodging_limit_table"], {"*": {"*": 120_000},
                                                                "국내": {"*": 120_000, "B": 120_000}})

    def test_amount_over_threshold_now_fires_instead_of_silently_passing(self):
        """이 작업의 인수 조건 — 조립기 연결 전에는 통과(PASS)로 보이던 건이 실제로 잡힌다."""
        snapshot = {
            "entry_node_key": "n1",
            "nodes": [{"node_key": "n1",
                       "condition": {"and": [
                           {">": [{"var": "tx.amount"}, {"var": "policy.preapproval_threshold"}]},
                           {"==": [{"var": "approval.pre_approval_obtained"}, False]}]},
                       "action": {"decision": "RETURN", "flag": "PRE_APPROVAL_MISSING"}}],
            "routings": [],
        }
        ctx = empty_eval_context()
        ctx["tx"]["amount"] = 620_000
        ctx["approval"]["pre_approval_obtained"] = False
        resolve_policy(ctx, load_tables())

        result = run_rule_engine(ctx, snapshot)
        self.assertEqual(result.decision, "RETURN")
        self.assertEqual(result.flags, ["PRE_APPROVAL_MISSING"])

    def test_policy_lookup_api_keeps_draft_agent_contract(self):
        """Draft Agent(get_policy)의 응답 계약은 Policy 폐기 후에도 그대로다."""
        response = self.client.get("/api/internal/policies/접대/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["category"], "접대")
        self.assertEqual(body["limit_amount"], 30_000)
        self.assertEqual(body["required_evidence"], ["영수증"])
        self.assertTrue(body["refs"])


class AttachmentExtractionTests(TestCase):
    """첨부 문서 추출 → EvalContext 반영 (`_context/evidence-extraction-agent.md`)."""

    def setUp(self):
        upsert_all()
        from django.contrib.auth import get_user_model
        from domain.cards.models import Card, CardType
        from domain.settlements.models import Attachment, Settlement
        from domain.transactions.models import Transaction

        user = get_user_model().objects.create(username="tester")
        card = Card.objects.create(card_type=CardType.PERSONAL, name="개인", owner=user)
        tx = Transaction.objects.create(card=card, merchant="한우명가", amount=300_000,
                                        ts=timezone.now())
        self.settlement = Settlement.objects.create(
            transaction=tx, category="접대", purpose="거래처 미팅", submitted_by=user,
        )
        self.Attachment = Attachment

    def _attach(self, kind, extracted, **kwargs):
        return self.Attachment.objects.create(
            settlement=self.settlement, kind=kind, extraction_status="DONE",
            extracted=extracted, extracted_at=timezone.now(), **kwargs,
        )

    def test_extracted_facts_land_in_context(self):
        self._attach("MEETING_MINUTES", {"participants.participant_count": 4})
        ctx, _ = build_rule_context(settlement=self.settlement)
        self.assertEqual(ctx["participants"]["participant_count"], 4)

    def test_user_input_beats_extraction(self):
        """사람이 확정한 컬럼값이 추출값을 이긴다."""
        self._attach("MEETING_MINUTES", {"participants.participant_count": 4})
        self.settlement.headcount = 6
        self.settlement.save(update_fields=["headcount"])
        ctx, _ = build_rule_context(settlement=self.settlement)
        self.assertEqual(ctx["participants"]["participant_count"], 6)

    def test_empty_column_does_not_erase_extraction(self):
        """컬럼이 비어 있어도(모름) 추출값을 지우지 않는다."""
        self._attach("PRE_APPROVAL", {"approval.pre_approval_obtained": True})
        self.assertIsNone(self.settlement.pre_approved)
        ctx, _ = build_rule_context(settlement=self.settlement)
        self.assertIs(ctx["approval"]["pre_approval_obtained"], True)

    def test_unknown_path_from_extractor_is_ignored(self):
        """추출기가 스키마에 없는 경로를 보내도 판정이 깨지지 않는다."""
        self._attach("TRIP_PLAN", {"trip.flight_class": "BUSINESS",
                                   "trip.trip_type": "국내"})
        ctx, _ = build_rule_context(settlement=self.settlement)
        self.assertEqual(ctx["trip"]["trip_type"], "국내")
        self.assertNotIn("flight_class", ctx["trip"])

    def test_pending_extraction_is_not_applied(self):
        self._attach("MEETING_MINUTES", {"participants.participant_count": 9})
        self.Attachment.objects.update(extraction_status="PENDING")
        ctx, _ = build_rule_context(settlement=self.settlement)
        self.assertIsNone(ctx["participants"]["participant_count"])
