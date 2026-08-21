"""Sentinel schema validation + repair.

Validates tool_call arguments against the tool's declared JSON Schema.
Repairs common hallucination patterns: fuzzy enum match, type coercion, defaults.
"""

from __future__ import annotations

from difflib import get_close_matches
from typing import Any

from maistro.security._types import SentinelVerdict, Violation


def _check_required_fields(
    args: dict[str, Any],
    properties: dict[str, Any],
    required: set[str],
    repaired: dict[str, Any],
    violations: list[Violation],
) -> bool:
    """Check required fields; fill defaults where available. Returns True if any
    repair (default substitution) was applied."""
    was_repaired = False
    for field_name in required:
        if field_name in args:
            continue
        field_schema = properties.get(field_name, {})
        if "default" in field_schema:
            repaired[field_name] = field_schema["default"]
            was_repaired = True
            violations.append(
                Violation(
                    boundary="system_to_tool",
                    rule="missing_required_with_default",
                    severity="info",
                    detail=f"Missing '{field_name}', used default",
                    repair_action=f"default={field_schema['default']}",
                )
            )
        else:
            violations.append(
                Violation(
                    boundary="system_to_tool",
                    rule="missing_required",
                    severity="error",
                    detail=f"Required field '{field_name}' missing",
                )
            )
    return was_repaired


def _repair_unknown_field(
    field_name: str,
    properties: dict[str, Any],
    repaired: dict[str, Any],
    violations: list[Violation],
) -> bool:
    """Fuzzy-rename an unknown field to the closest known property. Returns True
    if a rename was applied."""
    close = get_close_matches(field_name, properties.keys(), n=1, cutoff=0.6)
    if not close:
        return False
    repaired[close[0]] = repaired.pop(field_name)
    violations.append(
        Violation(
            boundary="system_to_tool",
            rule="field_name_fuzzy_match",
            severity="warning",
            detail=f"'{field_name}' -> '{close[0]}'",
            repair_action=f"renamed to {close[0]}",
        )
    )
    return True


def _repair_enum(
    field_name: str,
    value: Any,
    field_schema: dict[str, Any],
    repaired: dict[str, Any],
    violations: list[Violation],
) -> bool:
    """Validate/fuzzy-repair an enum field. Returns True if a repair was applied."""
    if "enum" not in field_schema or value in field_schema["enum"]:
        return False
    enum_strs = [str(e) for e in field_schema["enum"]]
    close = get_close_matches(str(value), enum_strs, n=1, cutoff=0.6)
    if close:
        matched_idx = enum_strs.index(close[0])
        repaired[field_name] = field_schema["enum"][matched_idx]
        violations.append(
            Violation(
                boundary="system_to_tool",
                rule="enum_fuzzy_match",
                severity="warning",
                detail=f"'{value}' -> '{close[0]}'",
                repair_action=f"matched to {close[0]}",
            )
        )
        return True
    violations.append(
        Violation(
            boundary="system_to_tool",
            rule="invalid_enum",
            severity="error",
            detail=f"'{value}' not in {field_schema['enum']}",
        )
    )
    return False


def _repair_type(
    field_name: str,
    value: Any,
    field_schema: dict[str, Any],
    repaired: dict[str, Any],
    violations: list[Violation],
) -> bool:
    """Validate/coerce a field's type. Returns True if a coercion was applied."""
    expected_type = field_schema.get("type")
    if not expected_type or _type_matches(value, expected_type):
        return False
    coerced = _try_coerce(value, expected_type)
    if coerced is not None:
        repaired[field_name] = coerced
        violations.append(
            Violation(
                boundary="system_to_tool",
                rule="type_coercion",
                severity="warning",
                detail=f"Coerced {type(value).__name__} -> {expected_type}",
                repair_action=f"coerced to {expected_type}",
            )
        )
        return True
    violations.append(
        Violation(
            boundary="system_to_tool",
            rule="type_mismatch",
            severity="error",
            detail=f"Expected {expected_type}, got {type(value).__name__}",
        )
    )
    return False


def validate_and_repair(
    args: dict[str, Any],
    schema: dict[str, Any],
) -> SentinelVerdict:
    violations: list[Violation] = []
    repaired = dict(args)

    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    was_repaired = _check_required_fields(args, properties, required, repaired, violations)

    for field_name, value in list(repaired.items()):
        field_schema = properties.get(field_name)

        if field_schema is None:
            if _repair_unknown_field(field_name, properties, repaired, violations):
                was_repaired = True
            continue

        if _repair_enum(field_name, value, field_schema, repaired, violations):
            was_repaired = True

        if _repair_type(field_name, value, field_schema, repaired, violations):
            was_repaired = True

    has_errors = any(v.severity == "error" for v in violations)
    if has_errors and not was_repaired:
        return SentinelVerdict(
            allowed=False,
            violations=tuple(violations),
        )

    return SentinelVerdict(
        allowed=True,
        repaired=was_repaired,
        repaired_data=repaired if was_repaired else None,
        violations=tuple(violations),
    )


def _type_matches(value: object, expected: str) -> bool:
    type_map: dict[str, tuple[type, ...]] = {
        "string": (str,),
        "integer": (int,),
        "number": (int, float),
        "boolean": (bool,),
        "array": (list,),
        "object": (dict,),
    }
    return isinstance(value, type_map.get(expected, (object,)))


def _try_coerce(value: object, target_type: str) -> object | None:
    try:
        if target_type == "string":
            return str(value)
        if target_type == "integer":
            return int(str(value))
        if target_type == "number":
            return float(str(value))
        if target_type == "boolean":
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes")
            return bool(value)
    except (ValueError, TypeError):
        pass
    return None
