from django.test import SimpleTestCase

from domain.policies.engine import GraphValidationError, run_rule_engine, validate_graph
from domain.policies.eval_context import validate_graph_vars


def graph(nodes, routings, entry="first"):
    return {"entry_node_key": entry, "nodes": nodes, "routings": routings}


class EngineTests(SimpleTestCase):
    def test_deterministic_traversal_and_flags(self):
        snapshot = graph(
            [
                {"node_key": "first", "condition": {">": [{"var": "tx.amount"}, 30_000]}, "action": {"decision": "PASS_THROUGH", "flag": "HIGH_AMOUNT"}},
                {"node_key": "review", "condition": True, "action": {"decision": "REVIEW", "flag": "NEEDS_REVIEW"}},
            ],
            [{"from_node_key": "first", "on_result": "MATCH", "to_node_key": "review", "priority": 0}],
        )
        ctx = {"tx": {"amount": 45_000}}
        first = run_rule_engine(ctx, snapshot)
        second = run_rule_engine(ctx, snapshot)
        self.assertEqual(first, second)
        self.assertEqual(first.decision, "REVIEW")
        self.assertEqual(first.path, ["first", "review"])
        self.assertEqual(first.flags, ["HIGH_AMOUNT", "NEEDS_REVIEW"])

    def test_priority_selects_first_route(self):
        snapshot = graph(
            [
                {"node_key": "first", "condition": True, "action": {"decision": "PASS_THROUGH"}},
                {"node_key": "pass", "condition": True, "action": {"decision": "PASS"}},
                {"node_key": "review", "condition": True, "action": {"decision": "REVIEW"}},
            ],
            [
                {"from_node_key": "first", "on_result": "MATCH", "to_node_key": "review", "priority": 10},
                {"from_node_key": "first", "on_result": "MATCH", "to_node_key": "pass", "priority": 1},
            ],
        )
        self.assertEqual(run_rule_engine({}, snapshot).decision, "PASS")

    def test_cycle_is_rejected_and_runtime_fails_safe(self):
        snapshot = graph(
            [{"node_key": "first", "condition": True, "action": {"decision": "PASS_THROUGH"}}],
            [{"from_node_key": "first", "on_result": "MATCH", "to_node_key": "first", "priority": 0}],
        )
        with self.assertRaises(GraphValidationError):
            validate_graph(snapshot)
        self.assertEqual(run_rule_engine({}, snapshot).decision, "REVIEW")
        self.assertEqual(run_rule_engine({}, snapshot).flags, ["INVALID_RULE_GRAPH"])

    def test_unknown_eval_context_var_is_reported(self):
        snapshot = graph(
            [{"node_key": "first", "condition": {"var": "tx.not_defined"}, "action": {"decision": "PASS"}}],
            [],
        )
        self.assertEqual(validate_graph_vars(snapshot), {"tx.not_defined"})
