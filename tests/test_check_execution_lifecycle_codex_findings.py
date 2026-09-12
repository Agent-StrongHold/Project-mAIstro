"""Fixes for the Codex review round on ed7fd3b (#1136): global rebinding,
PEP 613 explicit ``TypeAlias`` strings, and PEP 695 type-parameter shadowing.

Each case here was independently reproduced against the scanner before this
change and confirmed to misbehave; the assertions below are what a correct
static reading of the same source actually is.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATES = {"PENDING", "RUNNING", "FAILED"}


@pytest.fixture(scope="module")
def gate():
    path = ROOT / "scripts" / "check-execution-lifecycles.py"
    spec = importlib.util.spec_from_file_location("_lifecycle_codex_findings_gate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_global_declaration_gets_the_module_scope_identity(gate) -> None:
    """``global RunStatus`` makes the assignment a module-level identity, not
    the function-qualified one the assignment's lexical position suggests --
    the scanner previously reported this as ``pkg.mod::configure.RunStatus``,
    which could let an already-authorized local-scoped name mask a distinct
    new global execution authority."""
    source = """from typing import Literal
def configure():
    global RunStatus
    RunStatus = Literal["pending", "running", "failed"]
"""
    assert gate.work_state_literals(source, "pkg.mod") == {
        "pkg.mod::RunStatus": STATES,
    }


def test_global_declaration_does_not_leak_into_functions_without_it(gate) -> None:
    """A sibling function assigning the same name without ``global`` keeps
    its own function-qualified identity; the fix must not conflate the two."""
    source = """from typing import Literal
def configure():
    global RunStatus
    RunStatus = Literal["pending", "running", "failed"]
def other():
    RunStatus = Literal["queued", "done", "errored"]
"""
    assert gate.work_state_literals(source, "pkg.mod") == {
        "pkg.mod::RunStatus": STATES,
        "pkg.mod::other.RunStatus": {"QUEUED", "DONE", "ERRORED"},
    }


def test_explicit_type_alias_string_is_parsed_as_a_type_expression(gate) -> None:
    """PEP 613: ``x: TypeAlias = "..."`` is an explicit alias whose quoted RHS
    is type syntax, not a runtime string value -- Pyright treats it the same
    way. The scanner previously left this as opaque string data and reported
    no vocabulary at all."""
    source = """from typing import TypeAlias
RunStatus: TypeAlias = "Literal['pending', 'running', 'failed']"
"""
    assert gate.work_state_literals(source, "pkg.mod") == {
        "pkg.mod::RunStatus": STATES,
    }


def test_ordinary_string_assignment_is_still_not_a_type_alias(gate) -> None:
    """Without an explicit ``TypeAlias`` annotation, a quoted string stays
    inert data -- the PEP 613 carve-out must not swallow every string."""
    source = """
RunStatus = "Literal['pending', 'running', 'failed']"
"""
    assert gate.work_state_literals(source, "pkg.mod") == {}


def test_type_alias_annotated_non_type_string_is_still_ignored(gate) -> None:
    """A ``TypeAlias``-annotated string that isn't valid type syntax must not
    be treated as a lifecycle -- only interpret it, never execute or trust it
    blindly."""
    source = """from typing import TypeAlias
Greeting: TypeAlias = "just a friendly greeting"
"""
    assert gate.work_state_literals(source, "pkg.mod") == {}


def test_pep695_type_parameter_shadows_the_outer_binding(gate) -> None:
    """``type RunStatus[Values] = Values`` introduces ``Values`` as a type
    parameter local to the alias; it must not resolve to an unrelated outer
    ``Values`` alias of the same name. The scanner previously resolved the
    outer binding and falsely reported a lifecycle here."""
    source = """from typing import Literal
Values = Literal["pending", "running", "failed"]
type RunStatus[Values] = Values
"""
    assert gate.work_state_literals(source, "pkg.mod") == {}


def test_pep695_type_parameter_on_class_shadows_the_outer_binding(gate) -> None:
    """The same masking applies to a generic class's own type parameters."""
    source = """from typing import Literal
T = Literal["pending", "running", "failed"]
class Box[T]:
    status: T
"""
    assert gate.work_state_literals(source, "pkg.mod") == {}


def test_pep695_generic_alias_still_resolves_when_not_shadowed(gate) -> None:
    """A generic alias whose value does *not* reuse a type-parameter name
    still resolves normally -- the fix must only mask the shadowed name."""
    source = """from typing import Literal
RunStatus = Literal["pending", "running", "failed"]
type Stage[T] = RunStatus
"""
    assert gate.work_state_literals(source, "pkg.mod") == {
        "pkg.mod::RunStatus": STATES,
        "pkg.mod::Stage": STATES,
    }
