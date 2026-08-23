"""안전한 JSON-Logic 부분집합 evaluator (기술명세서 §4.2(d), FR-RA-09)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


MAX_DEPTH = 32
LOGIC_OPERATORS = {"and", "or", "not"}
COMPARE_OPERATORS = {"==", "!=", ">", ">=", "<", "<=", "in"}
#: 모름(None)을 참으로 만들 수 있는 **유일한** 연산자. 아래 `_evaluate` 주석 참조.
NULL_TEST = "is_null"
OPERATORS = LOGIC_OPERATORS | COMPARE_OPERATORS | {"var", NULL_TEST}


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
    if operator in ("not", NULL_TEST):
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
        or any(not isinstance(item, (bool, int, float, str)) for item in args[1])
    ):
        # `null`을 허용하면 조용히 아무것도 안 맞는다(좌변 None에서 먼저 끊긴다) —
        # "왜 안 걸리지"를 만드는 자리라 문법에서 막는다. 모름 판정은 `is_null`로.
        raise DSLValidationError("in의 우변은 null이 아닌 리터럴 리스트여야 합니다.")
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


def guarded_vars(expr: Any) -> set[str]:
    """조건식이 참조하는 경로 중 **미해소 가드가 봐야 할 것**만 추출한다.

    `is_null`이 감싼 경로는 뺀다 — 거기서는 `None`이 「판단할 수 없음」이 아니라 **묻고 있는
    값 자체**라, 가드가 강등하면 그 룰은 영영 참이 될 수 없다(연산자만 넣고 가드를 그대로 두면
    `is_null`은 아무 뜻이 없다).

    **같은 경로가 `is_null` 밖에도 나오면 가드를 유지한다.** 한 노드가
    `is_null(x) or x > 5`처럼 쓰면 뒤쪽 비교는 여전히 x를 알아야 뜻이 있다 — 애매하면
    안전한 쪽(강등)으로 붙인다.
    """
    validate_expr(expr)
    outside: set[str] = set()

    def visit(value: Any, *, under_null: bool) -> None:
        if isinstance(value, Mapping):
            operator, args = next(iter(value.items()))
            if operator == "var":
                if not under_null:
                    outside.add(args)
            else:
                visit(args, under_null=under_null or operator == NULL_TEST)
        elif isinstance(value, list):
            for item in value:
                visit(item, under_null=under_null)

    visit(expr, under_null=False)
    return outside


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
    if operator == NULL_TEST:
        return _evaluate(args, ctx) is None
    if operator == "not":
        # 모름의 부정도 참이 아니다. `not(x)`가 모름을 참으로 만들면 「확인 안 함」이
        # 「없음」으로 판정된다(실측: T-21이 증빙 미확인 건에 EVIDENCE_MISSING을 달았다).
        value = _evaluate(args, ctx)
        return False if value is None else not bool(value)

    left = _evaluate(args[0], ctx)
    right = _evaluate(args[1], ctx)
    # **모름은 어느 방향으로도 참을 만들지 않는다.** 비교에 None이 하나라도 끼면 False다
    # — 연산자마다 다르게 굴면(예전 `!=`는 모를 때 참이었다) 그 예외를 룰 작성자와 LLM이
    # 매번 기억해야 하고, 틀리는 방향이 「조용한 위반 판정」이 된다. 모름을 묻고 싶으면
    # `is_null`을 쓴다 — 이름이 곧 뜻이라 읽는 사람이 되짚을 필요가 없다.
    if left is None or right is None:
        return False
    if operator == "==":
        return _same_comparable_type(left, right) and left == right
    if operator == "!=":
        return _same_comparable_type(left, right) and left != right
    if operator == "in":
        return left in right
    if not _same_comparable_type(left, right):
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
