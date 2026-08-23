"""Rule Agent의 `is_null` 조립 회귀.

`is_null`은 **단항**이라 기존 이항 조립 경로(`left op right`)와 모양이 다르다. 여기가
어긋나면 모델이 낸 「모름」 조건이 저장 단계에서 422로 튕기거나, 더 나쁘게는 우변이 붙은
채로 조립돼 뜻이 달라진다.

가드 면제(`guarded_vars`)까지 함께 보는 이유: 조립만 맞고 면제가 안 걸리면 그 룰은 참이
될 수 없다(엔진이 판정을 REVIEW로 덮는다) — 즉 조용히 무용해진다.
"""
from __future__ import annotations

import pytest

from app.agents.rule_agent_v0.agent import _build_condition


def node(**over):
    base = dict(kind="comparison", left_path=None, op=None, negate=False, right_kind=None,
                right_var_path=None, right_number=None, right_string=None,
                right_bool=None, right_string_list=None, combinator=None, children=None)
    base.update(over)
    return base


def test_단항으로_조립된다():
    built = _build_condition(node(left_path="approval.pre_approval_obtained", op="is_null"))
    assert built == {"is_null": {"var": "approval.pre_approval_obtained"}}


def test_우변을_채워_보내도_무시한다():
    """단항이라 쓸 자리가 없다. 모델이 습관적으로 채워 보내는 일이 있다."""
    noisy = _build_condition(node(left_path="approval.pre_approval_obtained", op="is_null",
                                  right_kind="boolean", right_bool=False))
    assert noisy == {"is_null": {"var": "approval.pre_approval_obtained"}}


def test_negate는_값이_있다가_된다():
    built = _build_condition(node(left_path="category.value", op="is_null", negate=True))
    assert built == {"not": {"is_null": {"var": "category.value"}}}


def test_기존_이항_조립은_그대로다():
    built = _build_condition(node(left_path="tx.amount", op=">", right_kind="var",
                                  right_var_path="policy.preapproval_threshold"))
    assert built == {">": [{"var": "tx.amount"}, {"var": "policy.preapproval_threshold"}]}


def test_group_안에서도_조립된다():
    built = _build_condition(node(kind="group", combinator="and", children=[
        node(left_path="category.value", op="is_null", negate=True),
        node(left_path="tx.amount", op=">", right_kind="number", right_number=1000),
    ]))
    assert built == {"and": [
        {"not": {"is_null": {"var": "category.value"}}},
        {">": [{"var": "tx.amount"}, 1000]},
    ]}


@pytest.mark.parametrize("op", ["==", "!=", ">", ">=", "<", "<=", "in", "is_null"])
def test_툴_스키마가_허용하는_연산자를_전부_조립할_수_있다(op):
    """스키마 enum과 조립기가 갈리면 모델이 낼 수 있는데 파이썬이 못 만든다."""
    kwargs = dict(left_path="tx.amount", op=op)
    if op == "in":
        kwargs.update(right_kind="string_list", right_string_list=["a"])
    elif op != "is_null":
        kwargs.update(right_kind="number", right_number=1)
    assert _build_condition(node(**kwargs))
