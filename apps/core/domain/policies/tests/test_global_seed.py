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

    def test_clean_transaction_passes_global_gate(self):
        context = {
            "merchant": {"merchant_type": "문구점"},
            "category": {"item_type": "비품"},
            "tx": {"payment_method": "카드"},
        }
        result = run_rule_engine(context, self.graph)
        self.assertEqual(result.decision, "PASS")
        self.assertEqual(result.path, ["R-002", "R-003", "_GLOBAL_PASS"])
