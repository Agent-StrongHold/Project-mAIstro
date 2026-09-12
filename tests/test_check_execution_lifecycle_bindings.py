"""Binding order and lexical masking in Literal lifecycle discovery (#1136)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
IMPORTS = "from typing import Literal\nfrom pkg.base import RunStatus as Shared\n"
EVIDENCE = {"CANCELLED", "<imported-type:pkg.base.RunStatus>"}


@pytest.fixture(scope="module")
def gate():
    path = ROOT / "scripts" / "check-execution-lifecycles.py"
    spec = importlib.util.spec_from_file_location("_lifecycle_binding_gate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "binding",
    ["def Shared(): pass", "async def Shared(): pass", "class Shared: pass"],
)
def test_local_definition_masks_imported_evidence(gate, binding: str) -> None:
    source = IMPORTS + (
        f"class Worker:\n    {binding}\n" '    Status = Shared | Literal["cancelled"]\n'
    )
    assert gate.work_state_literals(source, "pkg.worker") == {}


@pytest.mark.parametrize(
    "signature",
    ["Shared", "Shared, /", "*, Shared", "*Shared", "**Shared"],
)
def test_parameter_masks_an_outer_import(gate, signature: str) -> None:
    source = IMPORTS + (
        f"def make({signature}):\n" '    WorkerStatus = Shared | Literal["cancelled"]\n'
    )
    assert gate.work_state_literals(source, "pkg.worker") == {}


@pytest.mark.parametrize(
    ("setup", "expression"),
    [
        ("Shared = None\nfrom pkg.base import RunStatus as Shared", "Shared"),
        ("Shared = None\nimport pkg.base as Shared", "Shared.RunStatus"),
        ("def Shared(): pass\nfrom pkg.base import RunStatus as Shared", "Shared"),
    ],
)
def test_import_replaces_an_earlier_binding(gate, setup: str, expression: str) -> None:
    source = (
        f"from typing import Literal\n{setup}\n"
        f'WorkerStatus = {expression} | Literal["cancelled"]\n'
    )
    found = gate.work_state_literals(source, "pkg.worker")
    assert found == {"pkg.worker::WorkerStatus": EVIDENCE}
    assert gate.audit({"lifecycles": {}}, found)
    assert gate._unauthorized_additions(sorted(found), {}, set()) == list(found)


def test_parameter_can_be_rebound_by_a_local_import(gate) -> None:
    source = IMPORTS + """
def make(Shared):
    from pkg.base import RunStatus as Shared
    WorkerStatus = Shared | Literal["cancelled"]
"""
    assert gate.work_state_literals(source, "pkg.worker") == {"pkg.worker::make.WorkerStatus": EVIDENCE}


def test_relative_typing_module_is_not_the_standard_library(gate) -> None:
    source = """
from typing import Literal
from .typing import RunStatus
WorkerStatus = RunStatus | Literal["cancelled"]
"""
    assert gate.work_state_literals(source, "pkg.worker") == {
        "pkg.worker::WorkerStatus": {"CANCELLED", "<imported-type:.typing.RunStatus>"}
    }


def test_an_assignment_after_an_import_still_masks_it(gate) -> None:
    source = IMPORTS + """
Shared = None
WorkerStatus = Shared | Literal["cancelled"]
"""
    assert gate.work_state_literals(source, "pkg.worker") == {}


def test_relative_typing_import_does_not_define_a_standard_typing_form(gate) -> None:
    source = """
from .typing import Literal as L
class Worker:
    status: L["queued", "running", "failed"]
"""
    assert gate.work_state_literals(source, "pkg.worker") == {}
