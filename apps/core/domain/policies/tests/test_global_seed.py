from django.test import SimpleTestCase

from domain.common.management.commands.seed_rules import global_snapshot
from domain.policies.engine import run_rule_engine, validate_graph
from domain.policies.eval_context import validate_graph_vars


class GlobalRuleSeedTests(SimpleTestCase):
    def setUp(self):
        self.graph = global_snapshot()

    def test_snapshot_is_valid_and_uses_known_context_paths(self):
        validate_graph(self.graph)
        self.assertEqual(validate_graph_vars(self.graph), set())

    def test_forbidden_merchant_rejects_at_first_gate(self):
        result = run_rule_engine(
            {"merchant": {"merchant_type": "유흥업소"}, "category": {}, "tx": {}}, self.graph
        )
        self.assertEqual(result.decision, "REJECT")
        self.assertEqual(result.path, ["R-002"])

    def test_cash_gift_certificate_rejects_at_second_gate(self):
        context = {
            "merchant": {"merchant_type": "문구점"},
            "category": {"item_type": "상품권"},
            "tx": {"payment_method": "현금"},
        }
        result = run_rule_engine(context, self.graph)
        self.assertEqual(result.decision, "REJECT")
        self.assertEqual(result.path, ["R-002", "R-003"])

    def test_shared_card_without_actual_user_is_returned(self):
        """v2에서 추가된 공용카드 실사용자 게이트(R-004)."""
        context = {
            "merchant": {"merchant_type": "문구점"},
            "category": {"item_type": "비품"},
            "tx": {"payment_method": "카드"},
            "card": {"card_type": "SHARED", "actual_user_recorded": False},
        }
        result = run_rule_engine(context, self.graph)
        self.assertEqual(result.decision, "RETURN")
        self.assertEqual(result.path, ["R-002", "R-003", "R-004"])

    def test_late_night_personal_use_goes_to_review(self):
        """v3에서 추가된 심야 사적사용 의심 게이트(R-006)."""
        context = {
            "merchant": {"merchant_type": "문구점"},
            "category": {"item_type": "비품"},
            "tx": {"payment_method": "카드"},
            "card": {"card_type": "PERSONAL", "actual_user_recorded": True},
            "derived": {"is_late_night": True, "personal_use_suspected": True},
        }
        result = run_rule_engine(context, self.graph)
        self.assertEqual(result.decision, "REVIEW")
        self.assertEqual(result.path, ["R-002", "R-003", "R-004", "R-006"])

    def test_clean_transaction_passes_global_gate(self):
        context = {
            "merchant": {"merchant_type": "문구점"},
            "category": {"item_type": "비품"},
            "tx": {"payment_method": "카드"},
            "card": {"card_type": "PERSONAL", "actual_user_recorded": True},
            "derived": {"is_late_night": False, "personal_use_suspected": False},
        }
        result = run_rule_engine(context, self.graph)
        self.assertEqual(result.decision, "PASS")
        self.assertEqual(result.path, ["R-002", "R-003", "R-004", "R-006", "_GLOBAL_PASS"])
