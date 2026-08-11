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

    def test_unresolved_policy_var_demotes_to_review(self):
        """조립기가 별표를 해소하지 못하면 한도 룰이 조용히 미발동한다 — 가드가 이를 드러낸다."""
        snapshot = graph(
            [
                {"node_key": "first",
                 "condition": {">": [{"var": "tx.amount"}, {"var": "policy.preapproval_threshold"}]},
                 "action": {"decision": "PASS"}},
            ],
            [],
        )
        unresolved = run_rule_engine({"tx": {"amount": 620_000}, "policy": {}}, snapshot)
        self.assertEqual(unresolved.decision, "REVIEW")
        self.assertEqual(unresolved.flags, ["UNRESOLVED_POLICY_VAR:preapproval_threshold"])
        self.assertEqual(unresolved.confidence, 0.0)

        resolved = run_rule_engine(
            {"tx": {"amount": 620_000}, "policy": {"preapproval_threshold": 500_000}}, snapshot
        )
        self.assertEqual(resolved.decision, "PASS")
        self.assertEqual(resolved.flags, [])

    def test_unresolved_fact_demotes_with_its_own_flag(self):
        """정책값이 아닌 사실도 모르면 판정을 신뢰할 수 없다 — 고치는 방법이 달라 플래그를 분리한다."""
        snapshot = graph(
            [{"node_key": "first",
              "condition": {"==": [{"var": "approval.pre_approval_obtained"}, False]},
              "action": {"decision": "RETURN"}}],
            [],
        )
        result = run_rule_engine({"approval": {}}, snapshot)
        self.assertEqual(result.decision, "REVIEW")
        self.assertEqual(result.flags, ["UNRESOLVED_FACT:approval.pre_approval_obtained"])

    def test_explicit_false_is_not_unresolved(self):
        """계약: None은 '거짓'이 아니라 '모름'이다. 조립기가 False를 쓰면 정상 판정된다."""
        snapshot = graph(
            [{"node_key": "first",
              "condition": {"==": [{"var": "approval.pre_approval_obtained"}, False]},
              "action": {"decision": "RETURN", "flag": "PRE_APPROVAL_MISSING"}}],
            [],
        )
        result = run_rule_engine({"approval": {"pre_approval_obtained": False}}, snapshot)
        self.assertEqual(result.decision, "RETURN")
        self.assertEqual(result.flags, ["PRE_APPROVAL_MISSING"])

    def test_policy_and_fact_flags_coexist(self):
        snapshot = graph(
            [{"node_key": "first",
              "condition": {"and": [
                  {">": [{"var": "tx.amount"}, {"var": "policy.preapproval_threshold"}]},
                  {"==": [{"var": "approval.pre_approval_obtained"}, False]}]},
              "action": {"decision": "RETURN"}}],
            [],
        )
        result = run_rule_engine({"tx": {"amount": 1}, "policy": {}, "approval": {}}, snapshot)
        self.assertEqual(result.decision, "REVIEW")
        self.assertEqual(result.flags, [
            "UNRESOLVED_FACT:approval.pre_approval_obtained",
            "UNRESOLVED_POLICY_VAR:preapproval_threshold",
        ])

    def test_unresolved_guard_ignores_unvisited_nodes(self):
        """도달하지 않은 노드의 정책값 결측으로 과잉 강등하지 않는다."""
        snapshot = graph(
            [
                {"node_key": "first", "condition": True, "action": {"decision": "PASS"}},
                {"node_key": "never",
                 "condition": {">": [{"var": "tx.amount"}, {"var": "policy.lodging_limit"}]},
                 "action": {"decision": "REVIEW"}},
            ],
            [],
        )
        result = run_rule_engine({"tx": {"amount": 1}, "policy": {}}, snapshot)
        self.assertEqual(result.decision, "PASS")
        self.assertEqual(result.flags, [])

    def test_unknown_eval_context_var_is_reported(self):
        snapshot = graph(
            [{"node_key": "first", "condition": {"var": "tx.not_defined"}, "action": {"decision": "PASS"}}],
            [],
        )
        self.assertEqual(validate_graph_vars(snapshot), {"tx.not_defined"})
