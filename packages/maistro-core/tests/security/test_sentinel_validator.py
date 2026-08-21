"""Coverage for maistro.security.sentinel.validator (schema validation + repair)."""

from __future__ import annotations

from maistro.security._types import Violation
from maistro.security.sentinel.validator import (
    _check_required_fields,
    _repair_enum,
    _repair_type,
    _repair_unknown_field,
    _try_coerce,
    _type_matches,
    validate_and_repair,
)

# ─── _check_required_fields ───────────────────────────────────────────────────


def test_missing_required_field_with_default_is_repaired():
    repaired: dict = {}
    violations: list[Violation] = []
    was_repaired = _check_required_fields({}, {"x": {"default": 42}}, {"x"}, repaired, violations)
    assert was_repaired is True
    assert repaired == {"x": 42}
    assert len(violations) == 1
    assert violations[0].severity == "info"
    assert violations[0].rule == "missing_required_with_default"


def test_missing_required_field_without_default_is_error_not_repaired():
    repaired: dict = {}
    violations: list[Violation] = []
    was_repaired = _check_required_fields({}, {"x": {}}, {"x"}, repaired, violations)
    assert was_repaired is False
    assert repaired == {}
    assert violations[0].severity == "error"
    assert violations[0].rule == "missing_required"


def test_present_required_field_is_noop():
    repaired = {"x": 1}
    violations: list[Violation] = []
    was_repaired = _check_required_fields(
        {"x": 1}, {"x": {"default": 99}}, {"x"}, repaired, violations
    )
    assert was_repaired is False
    assert violations == []
    assert repaired == {"x": 1}


# ─── _repair_unknown_field ────────────────────────────────────────────────────


def test_unknown_field_fuzzy_renamed_when_close_match_exists():
    repaired = {"locaton": "NYC"}
    violations: list[Violation] = []
    result = _repair_unknown_field("locaton", {"location": {}}, repaired, violations)
    assert result is True
    assert repaired == {"location": "NYC"}
    assert violations[0].rule == "field_name_fuzzy_match"
    assert violations[0].severity == "warning"


def test_unknown_field_no_close_match_is_untouched():
    repaired = {"zzzzzzz": "val"}
    violations: list[Violation] = []
    result = _repair_unknown_field("zzzzzzz", {"location": {}}, repaired, violations)
    assert result is False
    assert repaired == {"zzzzzzz": "val"}
    assert violations == []


# ─── _repair_enum ──────────────────────────────────────────────────────────────


def test_enum_value_already_valid_is_noop():
    repaired = {"status": "active"}
    violations: list[Violation] = []
    result = _repair_enum(
        "status", "active", {"enum": ["active", "inactive"]}, repaired, violations
    )
    assert result is False
    assert violations == []
    assert repaired == {"status": "active"}


def test_enum_close_fuzzy_match_is_repaired():
    repaired = {"status": "activ"}
    violations: list[Violation] = []
    result = _repair_enum("status", "activ", {"enum": ["active", "inactive"]}, repaired, violations)
    assert result is True
    assert repaired == {"status": "active"}
    assert violations[0].rule == "enum_fuzzy_match"
    assert violations[0].severity == "warning"


def test_enum_no_close_match_is_error_not_repaired():
    repaired = {"status": "completely_unrelated_value"}
    violations: list[Violation] = []
    result = _repair_enum(
        "status",
        "completely_unrelated_value",
        {"enum": ["active", "inactive"]},
        repaired,
        violations,
    )
    assert result is False
    assert repaired == {"status": "completely_unrelated_value"}
    assert violations[0].rule == "invalid_enum"
    assert violations[0].severity == "error"


def test_field_schema_without_enum_key_is_noop():
    repaired = {"x": "anything"}
    violations: list[Violation] = []
    result = _repair_enum("x", "anything", {}, repaired, violations)
    assert result is False
    assert violations == []


# ─── _repair_type ──────────────────────────────────────────────────────────────


def test_type_already_matches_is_noop():
    repaired = {"count": 5}
    violations: list[Violation] = []
    result = _repair_type("count", 5, {"type": "integer"}, repaired, violations)
    assert result is False
    assert violations == []


def test_coercible_type_mismatch_is_repaired():
    repaired = {"count": "5"}
    violations: list[Violation] = []
    result = _repair_type("count", "5", {"type": "integer"}, repaired, violations)
    assert result is True
    assert repaired == {"count": 5}
    assert violations[0].rule == "type_coercion"
    assert violations[0].severity == "warning"


def test_non_coercible_type_mismatch_is_error_not_repaired():
    repaired = {"count": "abc"}
    violations: list[Violation] = []
    result = _repair_type("count", "abc", {"type": "integer"}, repaired, violations)
    assert result is False
    assert repaired == {"count": "abc"}
    assert violations[0].rule == "type_mismatch"
    assert violations[0].severity == "error"


def test_no_expected_type_in_schema_is_noop():
    repaired = {"x": "anything"}
    violations: list[Violation] = []
    result = _repair_type("x", "anything", {}, repaired, violations)
    assert result is False
    assert violations == []


# ─── _type_matches / _try_coerce ──────────────────────────────────────────────


def test_type_matches_bool_counts_as_integer_due_to_python_subclassing():
    # isinstance(True, int) is True in Python, so the "integer" type_map entry
    # (int,) accepts bools too -- documented quirk, not something this test fixes.
    assert _type_matches(True, "integer") is True


def test_type_matches_unknown_expected_type_falls_back_to_object_accepts_anything():
    assert _type_matches("anything", "totally-unknown-type") is True


def test_try_coerce_boolean_from_string_variants():
    assert _try_coerce("true", "boolean") is True
    assert _try_coerce("1", "boolean") is True
    assert _try_coerce("yes", "boolean") is True
    assert _try_coerce("no", "boolean") is False
    assert _try_coerce("garbage", "boolean") is False


def test_try_coerce_non_numeric_string_to_int_returns_none():
    assert _try_coerce("abc", "integer") is None


def test_try_coerce_non_numeric_string_to_number_returns_none():
    assert _try_coerce("abc", "number") is None


# ─── validate_and_repair (integration) ────────────────────────────────────────


def _schema():
    return {
        "properties": {
            "name": {"type": "string"},
            "count": {"type": "integer"},
            "status": {"type": "string", "enum": ["active", "inactive"]},
        },
        "required": ["name"],
    }


def test_all_valid_args_pass_with_no_repair():
    verdict = validate_and_repair({"name": "x", "count": 1, "status": "active"}, _schema())
    assert verdict.allowed is True
    assert verdict.repaired is False
    assert verdict.repaired_data is None
    assert verdict.violations == ()


def test_only_repairs_no_errors_allowed_with_repaired_data():
    verdict = validate_and_repair({"name": "x", "count": "5"}, _schema())
    assert verdict.allowed is True
    assert verdict.repaired is True
    assert verdict.repaired_data == {"name": "x", "count": 5}


def test_error_alongside_repair_still_allowed():
    # "count" has a non-coercible type error, but "status" is fuzzy-repaired.
    # The asymmetric rule: has_errors and not was_repaired -> deny. Since a
    # repair DID happen elsewhere, the error is overridden and allowed=True.
    verdict = validate_and_repair(
        {"name": "x", "count": "not-a-number", "status": "activ"}, _schema()
    )
    assert verdict.allowed is True
    assert any(v.severity == "error" for v in verdict.violations)
    assert any(v.severity == "warning" for v in verdict.violations)


def test_error_with_no_repair_at_all_is_denied():
    verdict = validate_and_repair({"name": "x", "count": "not-a-number"}, _schema())
    assert verdict.allowed is False
    assert verdict.repaired_data is None
    assert any(v.severity == "error" for v in verdict.violations)


def test_missing_required_field_with_no_default_denies():
    verdict = validate_and_repair({"count": 1}, _schema())
    assert verdict.allowed is False
    assert verdict.violations[0].rule == "missing_required"
