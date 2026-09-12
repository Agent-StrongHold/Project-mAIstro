"""Alias-resolution order, scope, and vocabulary edge cases (#1136 review round 3)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATES = {"QUEUED", "RUNNING", "FAILED"}


@pytest.fixture(scope="module")
def gate():
    path = ROOT / "scripts" / "check-execution-lifecycles.py"
    spec = importlib.util.spec_from_file_location("_lifecycle_scope_review_gate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_a_rebound_helper_does_not_retroactively_change_an_earlier_alias(gate) -> None:
    source = """from typing import Literal
Values = Literal["queued", "running", "failed"]
RunStatus = Values
Values = str
"""
    assert gate.work_state_literals(source, "pkg.worker") == {"pkg.worker::RunStatus": STATES}


def test_a_forward_reference_to_a_not_yet_defined_helper_finds_nothing(gate) -> None:
    """The reverse ordering must not invent a false lifecycle either."""
    source = """from typing import Literal
RunStatus = Values
Values = Literal["queued", "running", "failed"]
"""
    assert gate.work_state_literals(source, "pkg.worker") == {}


def test_a_quoted_pep604_union_operand_is_still_discovered(gate) -> None:
    source = """from typing import Literal
RunStatus = Literal["queued", "running"] | "Literal['failed']"
"""
    assert gate.work_state_literals(source, "pkg.worker") == {"pkg.worker::RunStatus": STATES}


def test_a_typing_import_shadowed_by_an_unrelated_one_is_not_treated_as_literal(gate) -> None:
    source = """from typing import Literal as L
from custom import Literal as L
RunStatus = L["queued", "running", "failed"]
"""
    assert gate.work_state_literals(source, "pkg.worker") == {}


def test_a_parameter_shadowing_a_typing_import_is_not_treated_as_literal(gate) -> None:
    source = """from typing import Literal as L
def handler(L):
    RunStatus = L["queued", "running", "failed"]
"""
    assert gate.work_state_literals(source, "pkg.worker") == {}


def test_class_scope_is_not_inherited_by_nested_classes_or_methods(gate) -> None:
    """A class body is not an enclosing lexical scope: a same-named class
    attribute in ``Outer`` must not shadow the real module-level vocabulary
    that ``Outer.Inner`` actually resolves to at runtime."""
    source = """from typing import Literal
_Values = Literal["queued", "running", "failed"]
class Outer:
    _Values = ["red", "green"]
    class Inner:
        RunStatus = _Values
"""
    assert gate.work_state_literals(source, "pkg.worker") == {
        "pkg.worker::Outer.Inner.RunStatus": STATES,
    }


def test_class_scope_is_not_inherited_by_a_nested_method_either(gate) -> None:
    source = """from typing import Literal
_Values = Literal["queued", "running", "failed"]
class Outer:
    _Values = ["red", "green"]
    def make(self):
        RunStatus = _Values
        return RunStatus
"""
    assert gate.work_state_literals(source, "pkg.worker") == {
        "pkg.worker::Outer.make.RunStatus": STATES,
    }


def test_final_backed_literal_members_are_resolved(gate) -> None:
    source = """from typing import Literal, Final
PENDING: Final = "pending"
RUNNING: Final = "running"
FAILED: Final = "failed"
RunStatus = Literal[PENDING, RUNNING, FAILED]
"""
    assert gate.work_state_literals(source, "pkg.worker") == {
        "pkg.worker::RunStatus": {"PENDING", "RUNNING", "FAILED"},
    }


def test_stage_named_lifecycle_aliases_are_discovered(gate) -> None:
    source = """from typing import Literal
ExecutionStage = Literal["queued", "running", "failed"]
"""
    assert gate.work_state_literals(source, "pkg.worker") == {
        "pkg.worker::ExecutionStage": STATES,
    }


def test_stage_named_fields_are_discovered_too(gate) -> None:
    source = """from typing import Literal
class Job:
    stage: Literal["queued", "running", "failed"]
"""
    assert gate.work_state_literals(source, "pkg.worker") == {"pkg.worker::Job.stage": STATES}
