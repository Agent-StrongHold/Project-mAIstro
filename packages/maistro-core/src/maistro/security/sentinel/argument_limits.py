"""Pre-schema resource limits for model/tool-call arguments.

Tool-call arguments are already materialized Python objects by the time they
reach Sentinel, so this gate cannot protect the upstream JSON parser. It does
bound the work Sentinel and the tool executor will perform: structural depth is
checked iteratively before serialization, then the compact UTF-8 JSON size is
bounded before schema validation or execution.

The shipped maxima are also the deployment security baseline. Operators may
tighten either limit freely. Raising a ceiling weakens the control and therefore
requires the same explicit ``ALLOW_UNSAFE_RESOURCE_OVERRIDES=true`` statement
used by the engine's other resource-security floors; an ordinary tuning env var
cannot silently widen the boundary.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from maistro.constants import TOOL_ARGUMENT_MAX_BYTES, TOOL_ARGUMENT_MAX_DEPTH
from maistro.security._types import Violation

_TOOL_ARGUMENT_MAX_BYTES_ENV = "MAISTRO_TOOL_ARGUMENT_MAX_BYTES"
_TOOL_ARGUMENT_MAX_DEPTH_ENV = "MAISTRO_TOOL_ARGUMENT_MAX_DEPTH"
_UNSAFE_RESOURCE_OVERRIDES_ENV = "ALLOW_UNSAFE_RESOURCE_OVERRIDES"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off", ""})


def _bool_env(name: str, default: bool = False) -> bool:
    """Read one explicit boolean policy flag, rejecting ambiguous spellings."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(
        f"{name} must be a boolean (true/false, 1/0, yes/no, on/off), got {raw!r}"
    )


def _protected_positive_int_env(
    name: str,
    default: int,
    *,
    unsafe_overrides_enabled: bool,
) -> int:
    """Read a positive maximum whose shipped value is the security floor.

    These settings are maxima, so a smaller value is tighter and a larger value
    is weaker. A weaker deployment is valid only when the operator separately
    opted into unsafe resource overrides; the override licenses a weaker value,
    never an incoherent one.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer, got {value}")
    if value > default and not unsafe_overrides_enabled:
        raise ValueError(
            f"{name}={value} weakens the declared security baseline of {default}; "
            f"set {_UNSAFE_RESOURCE_OVERRIDES_ENV}=true only for an explicit unsafe/dev deployment"
        )
    return value


@dataclass(frozen=True)
class ToolArgumentLimits:
    """Effective deployment policy for one Sentinel instance."""

    max_bytes: int = TOOL_ARGUMENT_MAX_BYTES
    max_depth: int = TOOL_ARGUMENT_MAX_DEPTH

    @classmethod
    def from_environment(cls) -> ToolArgumentLimits:
        """Read deployment policy; invalid or silently-weaker policy fails startup."""
        unsafe = _bool_env(_UNSAFE_RESOURCE_OVERRIDES_ENV)
        return cls(
            max_bytes=_protected_positive_int_env(
                _TOOL_ARGUMENT_MAX_BYTES_ENV,
                TOOL_ARGUMENT_MAX_BYTES,
                unsafe_overrides_enabled=unsafe,
            ),
            max_depth=_protected_positive_int_env(
                _TOOL_ARGUMENT_MAX_DEPTH_ENV,
                TOOL_ARGUMENT_MAX_DEPTH,
                unsafe_overrides_enabled=unsafe,
            ),
        )


def _structural_depth(value: object, *, stop_after: int) -> int:
    """Return container depth, stopping as soon as ``stop_after`` is exceeded."""
    max_seen = 0
    stack: list[tuple[object, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if not isinstance(current, (dict, list)):
            continue
        max_seen = max(max_seen, depth)
        if depth > stop_after:
            return depth
        children = current.values() if isinstance(current, dict) else current
        stack.extend((child, depth + 1) for child in children if isinstance(child, (dict, list)))
    return max_seen


def check_argument_limits(
    args: dict[str, Any],
    *,
    limits: ToolArgumentLimits,
) -> Violation | None:
    """Return an error violation when tool arguments exceed configured limits.

    Depth is checked first without recursion so deeply nested payloads are
    rejected before JSON serialization. Size is measured as compact UTF-8 JSON,
    matching the wire representation closely enough to make ASCII, Unicode, and
    encoded-string payloads obey the same byte ceiling.
    """
    depth = _structural_depth(args, stop_after=limits.max_depth)
    if depth > limits.max_depth:
        return Violation(
            boundary="pre_call",
            rule="tool_argument_depth_limit",
            severity="error",
            detail=f"Tool arguments depth {depth} exceeds configured maximum {limits.max_depth}",
        )

    try:
        encoded = json.dumps(
            args,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        return Violation(
            boundary="pre_call",
            rule="tool_argument_not_json",
            severity="error",
            detail="Tool arguments are not valid JSON-compatible data",
        )

    size = len(encoded)
    if size > limits.max_bytes:
        return Violation(
            boundary="pre_call",
            rule="tool_argument_size_limit",
            severity="error",
            detail=f"Tool arguments size {size} bytes exceeds configured maximum {limits.max_bytes}",
        )
    return None
