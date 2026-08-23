"""v6 null 의미론 + `is_null` 가드 면제 회귀.

가드는 이 시스템에서 **조용한 통과를 막는 유일한 장치**다. `is_null`은 거기에 구멍을
하나 뚫는 일이라, 그 구멍이 정확히 필요한 만큼만 열리는지를 여기서 고정한다.

고정하는 계약 넷:
① 모름은 어느 방향으로도 참을 만들지 않는다 (`is_null` 제외).
② `is_null`이 감싼 경로만 가드에서 빠진다.
③ 같은 경로가 `is_null` **밖에도** 나오면 가드를 유지한다 — 애매하면 안전한 쪽.
④ 면제는 가드에만 적용된다. ACTIVE 전환 게이트는 여전히 그 경로가 스키마에 있길 요구한다.
"""
from __future__ import annotations

from django.test import SimpleTestCase

from domain.policies.dsl import evaluate, extract_vars, guarded_vars
from domain.policies.engine import run_rule_engine
from domain.policies.eval_context import validate_graph_vars
from domain.policies.flags import SystemFlag

KNOWN = {"tx": {"amount": 45_000}, "merchant": {"merchant_type": None}}


def graph(condition, decision="PASS"):
    """조건 하나짜리 단말 그래프 — 판정과 플래그만 본다."""
    return {
        "entry_node_key": "n1",
        "nodes": [{"node_key": "n1", "condition": condition,
                   "action": {"decision": decision}}],
        "routings": [],
    }


class NullSemanticsTests(SimpleTestCase):
    """① 모름은 참을 만들지 않는다"""

    def test_모든_비교가_거짓이다(self):
        for expr in (
            {"==": [{"var": "merchant.merchant_type"}, "카페"]},
            {"!=": [{"var": "merchant.merchant_type"}, "카페"]},
            {"==": [{"var": "merchant.merchant_type"}, None]},
            {">": [{"var": "merchant.merchant_type"}, 0]},
            {"in": [{"var": "merchant.merchant_type"}, ["카페", "주점/유흥"]]},
            {"not": {"var": "merchant.merchant_type"}},
        ):
            with self.subTest(expr=expr):
                self.assertFalse(evaluate(expr, KNOWN))

    def test_두_경로가_모두_모름이어도_같다고_하지_않는다(self):
        """예전 `==`는 `left is right`라 둘 다 None이면 참이었다."""
        ctx = {"a": {"x": None}, "b": {"y": None}}
        self.assertFalse(evaluate({"==": [{"var": "a.x"}, {"var": "b.y"}]}, ctx))

    def test_아는_값은_평소대로_비교된다(self):
        self.assertTrue(evaluate({">": [{"var": "tx.amount"}, 30_000]}, KNOWN))
        self.assertTrue(evaluate({"!=": [{"var": "tx.amount"}, 1]}, KNOWN))
        self.assertFalse(evaluate({"not": {"==": [{"var": "tx.amount"}, 45_000]}}, KNOWN))


class GuardExemptionTests(SimpleTestCase):
    """②③ 면제 범위"""

    def test_is_null이_감싼_경로만_빠진다(self):
        expr = {"and": [{"is_null": {"var": "merchant.merchant_type"}},
                        {">": [{"var": "tx.amount"}, 1]}]}
        self.assertEqual(guarded_vars(expr), {"tx.amount"})
        # 스키마 검증은 여전히 전부 본다(④).
        self.assertEqual(extract_vars(expr), {"merchant.merchant_type", "tx.amount"})

    def test_밖에도_나오면_가드를_유지한다(self):
        """`is_null(x) or x == "카페"` — 뒤쪽은 여전히 x를 알아야 뜻이 있다."""
        expr = {"or": [{"is_null": {"var": "merchant.merchant_type"}},
                       {"==": [{"var": "merchant.merchant_type"}, "카페"]}]}
        self.assertEqual(guarded_vars(expr), {"merchant.merchant_type"})

    def test_not_아래의_is_null도_면제된다(self):
        """「값이 있는가」 관용구(`not(is_null(x))`)가 강등되면 쓸 수 없다."""
        expr = {"not": {"is_null": {"var": "merchant.merchant_type"}}}
        self.assertEqual(guarded_vars(expr), set())


class EngineIntegrationTests(SimpleTestCase):
    """면제가 **실제 판정**에서 동작하는가 — 단위 함수가 아니라 이 경로가 계약이다."""

    def test_모름을_참조하면_판정이_강등된다(self):
        result = run_rule_engine(KNOWN, graph({"==": [{"var": "merchant.merchant_type"}, "카페"]}))
        self.assertEqual(result.decision, "REVIEW")
        self.assertIn(f"{SystemFlag.UNRESOLVED_FACT.value}:merchant.merchant_type", result.flags)

    def test_is_null로_물으면_강등되지_않고_판정이_선다(self):
        result = run_rule_engine(KNOWN, graph({"is_null": {"var": "merchant.merchant_type"}}, "REJECT"))
        self.assertEqual(result.decision, "REJECT")
        self.assertEqual(result.flags, [])

    def test_값이_있는가_관용구(self):
        """`not(is_null(x))` — 모르면 조건 불성립이지만 **강등도 아니다**."""
        expr = {"not": {"is_null": {"var": "merchant.merchant_type"}}}
        unknown = run_rule_engine(KNOWN, graph(expr, "PASS"))
        self.assertEqual(unknown.decision, "PASS")   # 조건 거짓 → 단말 액션 그대로
        self.assertEqual(unknown.flags, [])

        known = {"merchant": {"merchant_type": "카페"}}
        self.assertEqual(run_rule_engine(known, graph(expr, "PASS")).decision, "PASS")

    def test_면제는_스키마_검증을_통과시키지_않는다(self):
        """④ 없는 경로를 `is_null`로 감싸도 ACTIVE 전환에서는 막힌다."""
        missing = validate_graph_vars(
            {"nodes": [{"condition": {"is_null": {"var": "project.code"}}}]},
        )
        self.assertEqual(missing, {"project.code"})
