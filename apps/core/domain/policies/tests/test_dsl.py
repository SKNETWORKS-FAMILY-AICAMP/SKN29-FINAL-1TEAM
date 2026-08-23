from django.test import SimpleTestCase

from domain.policies.dsl import DSLValidationError, evaluate, extract_vars, validate_expr


class DSLTests(SimpleTestCase):
    def setUp(self):
        self.ctx = {"tx": {"amount": 45_000}, "merchant": {"forbidden": False}, "missing": None}

    def test_nested_expression_and_var_extraction(self):
        expr = {
            "and": [
                {">": [{"var": "tx.amount"}, 30_000]},
                {"==": [{"var": "merchant.forbidden"}, False]},
            ]
        }
        self.assertTrue(evaluate(expr, self.ctx))
        self.assertEqual(extract_vars(expr), {"tx.amount", "merchant.forbidden"})

    def test_모름은_어느_방향으로도_참을_만들지_않는다(self):
        """v6 — 연산자마다 다르게 굴면 그 예외를 룰 작성자와 LLM이 매번 기억해야 하고,
        틀리는 방향이 「조용한 위반 판정」이 된다."""
        for expr in (
            {"==": [{"var": "tx.unknown"}, None]},
            {"==": [{"var": "tx.unknown"}, 5]},
            {"!=": [{"var": "tx.unknown"}, 5]},        # 예전엔 참이었다(대표 함정)
            {">": [{"var": "tx.unknown"}, 0]},
            {"<=": [{"var": "tx.unknown"}, 0]},
            {"in": [{"var": "tx.unknown"}, [1, 2]]},
            {"not": {"var": "tx.unknown"}},            # 모름의 부정도 참이 아니다
        ):
            with self.subTest(expr=expr):
                self.assertFalse(evaluate(expr, self.ctx))

    def test_is_null만이_모름을_참으로_만든다(self):
        self.assertTrue(evaluate({"is_null": {"var": "tx.unknown"}}, self.ctx))
        self.assertFalse(evaluate({"is_null": {"var": "tx.amount"}}, self.ctx))
        # 「값이 있는가」 — `!= null` 관용구를 대체한다.
        self.assertTrue(evaluate({"not": {"is_null": {"var": "tx.amount"}}}, self.ctx))

    def test_in_우변에_null을_쓸_수_없다(self):
        """허용하면 조용히 아무것도 안 맞는다 — 좌변 None에서 먼저 끊기기 때문."""
        with self.assertRaises(DSLValidationError):
            validate_expr({"in": [{"var": "tx.amount"}, [1, None]]})

    def test_type_coercion_is_not_performed(self):
        self.assertFalse(evaluate({"==": [{"var": "tx.amount"}, "45000"]}, self.ctx))
        self.assertFalse(evaluate({"!=": [{"var": "tx.amount"}, "45000"]}, self.ctx))
        self.assertFalse(evaluate({">": [{"var": "tx.amount"}, "30000"]}, self.ctx))

    def test_in_requires_literal_list(self):
        self.assertTrue(evaluate({"in": [{"var": "tx.amount"}, [1, 45_000]]}, self.ctx))
        with self.assertRaises(DSLValidationError):
            validate_expr({"in": [{"var": "tx.amount"}, {"var": "limits"}]})

    def test_rejects_unknown_operator_and_excess_depth(self):
        with self.assertRaises(DSLValidationError):
            validate_expr({"eval": ["danger"]})
        expr = True
        for _ in range(34):
            expr = {"not": expr}
        with self.assertRaises(DSLValidationError):
            validate_expr(expr)
