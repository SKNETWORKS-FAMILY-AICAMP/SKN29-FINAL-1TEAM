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

    def test_missing_path_is_null_and_null_comparison_is_explicit(self):
        self.assertTrue(evaluate({"==": [{"var": "tx.unknown"}, None]}, self.ctx))
        self.assertFalse(evaluate({">": [{"var": "tx.unknown"}, 0]}, self.ctx))

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
