"""I29: Schema Validation + Repair — Hypothesis property-based tests."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from maistro.security._types import SentinelVerdict
from maistro.security.sentinel.validator import validate_and_repair


class ValidatorMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.schema = {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["read", "write", "delete"]},
                "target": {"type": "string"},
                "count": {"type": "integer"},
                "force": {"type": "boolean"},
            },
            "required": ["action", "target"],
        }

    @rule(
        action=st.sampled_from(["read", "write", "delete", "writ", "reed", "xyz"]),
        tgt=st.text(min_size=1, max_size=20),
        count_str=st.booleans(),
    )
    def try_validate(self, action, tgt, count_str):
        args = {"action": action, "target": tgt}
        if count_str:
            args["count"] = "5"
        verdict = validate_and_repair(args, self.schema)
        assert isinstance(verdict, SentinelVerdict)
        if action in ("read", "write", "delete"):
            assert verdict.allowed

    @invariant()
    def missing_required_without_default_is_error(self):
        verdict = validate_and_repair({}, self.schema)
        assert not verdict.allowed or any(v.severity == "error" for v in verdict.violations)

    @invariant()
    def valid_args_allowed(self):
        verdict = validate_and_repair({"action": "read", "target": "file.txt"}, self.schema)
        assert verdict.allowed


TestValidatorMachine = ValidatorMachine.TestCase


def test_missing_required_no_default_error():
    schema = {
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    verdict = validate_and_repair({}, schema)
    has_error = any(v.severity == "error" for v in verdict.violations)
    assert has_error


def test_missing_required_with_default_repaired():
    schema = {
        "properties": {"mode": {"type": "string", "default": "safe"}},
        "required": ["mode"],
    }
    verdict = validate_and_repair({}, schema)
    assert verdict.allowed
    assert verdict.repaired
    assert verdict.repaired_data["mode"] == "safe"


def test_invalid_enum_error():
    schema = {
        "properties": {"op": {"type": "string", "enum": ["read", "write"]}},
        "required": [],
    }
    verdict = validate_and_repair({"op": "xyz"}, schema)
    has_error = any(v.severity == "error" for v in verdict.violations)
    assert has_error


def test_fuzzy_enum_match_repaired():
    schema = {
        "properties": {"op": {"type": "string", "enum": ["read", "write"]}},
        "required": [],
    }
    verdict = validate_and_repair({"op": "writ"}, schema)
    assert verdict.allowed
    assert verdict.repaired
    assert verdict.repaired_data["op"] == "write"


def test_type_coercion_int_string():
    schema = {
        "properties": {"count": {"type": "integer"}},
        "required": [],
    }
    verdict = validate_and_repair({"count": "42"}, schema)
    assert verdict.allowed
    assert verdict.repaired
    assert verdict.repaired_data["count"] == 42


def test_type_coercion_bool_true():
    schema = {
        "properties": {"flag": {"type": "boolean"}},
        "required": [],
    }
    verdict = validate_and_repair({"flag": "true"}, schema)
    assert verdict.allowed
    assert verdict.repaired
    assert verdict.repaired_data["flag"] is True


def test_invalid_type_uncoercible_error():
    schema = {
        "properties": {"count": {"type": "integer"}},
        "required": [],
    }
    verdict = validate_and_repair({"count": "not_a_number"}, schema)
    has_error = any(v.severity == "error" for v in verdict.violations)
    assert has_error


def test_fuzzy_field_name_renamed():
    schema = {
        "properties": {"username": {"type": "string"}},
        "required": [],
    }
    verdict = validate_and_repair({"usrname": "alice"}, schema)
    assert verdict.allowed
    assert verdict.repaired
    assert "username" in verdict.repaired_data
    assert verdict.repaired_data["username"] == "alice"


def test_valid_args_allowed_no_repairs():
    schema = {
        "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
        "required": ["name"],
    }
    verdict = validate_and_repair({"name": "alice", "age": 30}, schema)
    assert verdict.allowed
    assert not verdict.repaired


@given(
    value=st.integers(min_value=0, max_value=100),
)
@settings(max_examples=30)
def test_valid_integers_pass(value):
    schema = {"properties": {"n": {"type": "integer"}}, "required": []}
    verdict = validate_and_repair({"n": value}, schema)
    assert verdict.allowed


@given(
    value=st.booleans(),
)
@settings(max_examples=20)
def test_valid_booleans_pass(value):
    schema = {"properties": {"b": {"type": "boolean"}}, "required": []}
    verdict = validate_and_repair({"b": value}, schema)
    assert verdict.allowed


@given(
    action=st.sampled_from(["read", "write", "delete"]),
    target=st.text(min_size=1, max_size=20),
)
@settings(max_examples=30)
def test_valid_enum_args_pass(action, target):
    schema = {
        "properties": {"action": {"type": "string", "enum": ["read", "write", "delete"]}, "target": {"type": "string"}},
        "required": ["action", "target"],
    }
    verdict = validate_and_repair({"action": action, "target": target}, schema)
    assert verdict.allowed
