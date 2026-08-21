"""Canonical condition parsing for graph edge predicates.

The graph execution authorities may store their state differently, but edge
conditions must mean the same thing everywhere. This module owns the small,
safe predicate dialect; callers supply only the path resolver for their state
representation.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

CONDITION_OPERATORS: Final = (
    " is not ",
    " is ",
    " >= ",
    " <= ",
    " != ",
    " == ",
    " > ",
    " < ",
)

MISSING = object()


def parse_condition_rhs(value: str) -> object:
    """Parse the literal right-hand side supported by graph predicates."""
    if value == "True":
        return True
    if value == "False":
        return False
    if value == "None":
        return None
    try:
        return float(value) if "." in value else int(value)
    except ValueError:
        return value.strip("\"'")


def compare_condition_values(lhs: object, operator: str, rhs: object) -> bool:
    """Compare two predicate values without evaluating arbitrary Python."""
    stripped = operator.strip()
    if stripped in ("is", "=="):
        return lhs == rhs
    if stripped in ("is not", "!="):
        return lhs != rhs

    # Operands come from runtime data and may have incompatible types.
    left: Any = lhs
    right: Any = rhs
    try:
        if stripped == "<":
            return bool(left < right)
        if stripped == ">":
            return bool(left > right)
        if stripped == "<=":
            return bool(left <= right)
        if stripped == ">=":
            return bool(left >= right)
    except TypeError:
        return False
    return False


def evaluate_predicate(condition: str, resolve_path: Callable[[str], object]) -> bool:
    """Evaluate one graph predicate using a caller-provided path resolver."""
    for operator in CONDITION_OPERATORS:
        if operator not in condition:
            continue
        lhs_text, rhs_text = condition.split(operator, 1)
        lhs = resolve_path(lhs_text.strip())
        if lhs is MISSING:
            return False
        rhs = parse_condition_rhs(rhs_text.strip())
        return compare_condition_values(lhs, operator, rhs)
    return False
