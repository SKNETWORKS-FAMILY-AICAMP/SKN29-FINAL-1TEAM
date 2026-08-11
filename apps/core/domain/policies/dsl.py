"""안전한 JSON-Logic 부분집합 evaluator (기술명세서 §4.2(d), FR-RA-09)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


MAX_DEPTH = 32
LOGIC_OPERATORS = {"and", "or", "not"}
COMPARE_OPERATORS = {"==", "!=", ">", ">=", "<", "<=", "in"}
OPERATORS = LOGIC_OPERATORS | COMPARE_OPERATORS | {"var"}


class DSLValidationError(ValueError):
    """조건식이 허용된 DSL 계약을 위반한 경우."""


def _validate(expr: Any, depth: int) -> None:
    if depth > MAX_DEPTH:
        raise DSLValidationError(f"조건식 최대 중첩 깊이({MAX_DEPTH})를 초과했습니다.")
    if expr is None or isinstance(expr, (bool, int, float, str)):
        return
    if isinstance(expr, list):
        for item in expr:
            _validate(item, depth + 1)
        return
    if not isinstance(expr, Mapping) or len(expr) != 1:
        raise DSLValidationError("식 객체는 하나의 연산자만 가져야 합니다.")

    operator, args = next(iter(expr.items()))
    if operator not in OPERATORS:
        raise DSLValidationError(f"허용되지 않은 연산자입니다: {operator}")
    if operator == "var":
        if not isinstance(args, str) or not args or any(not part for part in args.split(".")):
            raise DSLValidationError("var에는 유효한 dot-path 문자열이 필요합니다.")
        return
    if operator == "not":
        _validate(args, depth + 1)
        return
    if not isinstance(args, list):
        raise DSLValidationError(f"{operator}의 인자는 리스트여야 합니다.")
    if operator in {"and", "or"}:
        if not args:
            raise DSLValidationError(f"{operator}에는 하나 이상의 인자가 필요합니다.")
    elif len(args) != 2:
        raise DSLValidationError(f"{operator}에는 정확히 두 인자가 필요합니다.")
    if operator == "in" and (
        not isinstance(args[1], list)
        or any(item is not None and not isinstance(item, (bool, int, float, str)) for item in args[1])
    ):
        raise DSLValidationError("in의 우변은 리터럴 리스트여야 합니다.")
    for arg in args:
        _validate(arg, depth + 1)


def validate_expr(expr: Any) -> None:
    """조건식을 검증하고, 잘못된 식이면 ``DSLValidationError``를 발생시킨다."""
    _validate(expr, 0)


def extract_vars(expr: Any) -> set[str]:
    """검증된 조건식에서 참조하는 EvalContext 경로를 추출한다."""
    validate_expr(expr)
    found: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            operator, args = next(iter(value.items()))
            if operator == "var":
                found.add(args)
            else:
                visit(args)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(expr)
    return found


def resolve_path(ctx: Mapping[str, Any], path: str) -> Any:
    """dot-path로 컨텍스트 값을 읽는다. 없으면 ``None``(엔진의 미해소 판정이 이 값을 본다)."""
    value: Any = ctx
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


_resolve = resolve_path


def _same_comparable_type(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool)
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return True
    return type(left) is type(right)


def _evaluate(expr: Any, ctx: Mapping[str, Any]) -> Any:
    if not isinstance(expr, Mapping):
        return expr
    operator, args = next(iter(expr.items()))
    if operator == "var":
        return _resolve(ctx, args)
    if operator == "and":
        return all(bool(_evaluate(arg, ctx)) for arg in args)
    if operator == "or":
        return any(bool(_evaluate(arg, ctx)) for arg in args)
    if operator == "not":
        return not bool(_evaluate(args, ctx))

    left = _evaluate(args[0], ctx)
    right = _evaluate(args[1], ctx)
    if operator == "==":
        if left is None or right is None:
            return left is right
        return _same_comparable_type(left, right) and left == right
    if operator == "!=":
        if left is None or right is None:
            return left is not right
        return _same_comparable_type(left, right) and left != right
    if operator == "in":
        return False if left is None else left in right
    if left is None or right is None or not _same_comparable_type(left, right):
        return False
    try:
        if operator == ">":
            return left > right
        if operator == ">=":
            return left >= right
        if operator == "<":
            return left < right
        if operator == "<=":
            return left <= right
    except TypeError:
        return False
    return False


def evaluate(expr: Any, ctx: Mapping[str, Any]) -> bool:
    """검증 후 조건식을 순수 평가한다. 강제 타입 변환은 하지 않는다."""
    validate_expr(expr)
    return bool(_evaluate(expr, ctx))
