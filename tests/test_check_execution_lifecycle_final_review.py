"""Scoped Enum identity and postponed type expressions remain ledger-visible (#1136)."""

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
    spec = importlib.util.spec_from_file_location("_lifecycle_final_review_gate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("enclosing", ["class Outer:", "def make():", "async def make():"])
def test_nested_enums_do_not_authorize_top_level_literal_aliases(gate, enclosing: str) -> None:
    source = f"""from enum import Enum
from typing import Literal
{enclosing}
    class Status(Enum):
        QUEUED = "queued"
        RUNNING = "running"
        FAILED = "failed"
"""
    scope = "Outer" if enclosing.startswith("class") else "make"
    trusted = gate.work_state_enums(source, "pkg.worker")
    assert trusted == {f"pkg.worker::{scope}.Status": STATES}
    candidate = source + 'Status = Literal["queued", "running", "failed"]\n'
    found = gate.work_state_vocabularies(candidate, "pkg.worker")
    assert found == {**trusted, "pkg.worker::Status": STATES}
    entries = {name: {"classification": "DOMAIN", "rationale": "existing enum"} for name in trusted}
    assert any("pkg.worker::Status" in item for item in gate.audit({"lifecycles": entries}, found))
    assert gate._unauthorized_additions(sorted(found), {}, set(trusted)) == ["pkg.worker::Status"]
    assert gate.work_state_literals(candidate, "pkg.worker") == {"pkg.worker::Status": STATES}


def test_nested_enum_siblings_and_control_flow_keep_distinct_identities(gate) -> None:
    source = """from enum import Enum
class A:
    class Inner:
        class Status(Enum):
            QUEUED = "queued"
            RUNNING = "running"
            FAILED = "failed"
class B:
    if True:
        class Status(Enum):
            QUEUED = "queued"
            RUNNING = "running"
            FAILED = "failed"
"""
    assert gate.work_state_enums(source, "pkg.worker") == {
        "pkg.worker::A.Inner.Status": STATES,
        "pkg.worker::B.Status": STATES,
    }


@pytest.mark.parametrize(
    "annotation",
    [
        """'Literal["queued", "running", "failed"]'""",
        """'t.Literal["queued", "running", "failed"]'""",
        """'Optional[Literal["queued", "running", "failed"]]'""",
        """'Union[Literal["queued", "running"], Literal["failed"]]'""",
        """'Annotated[Literal["queued", "running", "failed"], "note"]'""",
        """Optional['Literal["queued", "running", "failed"]']""",
        """Union['Literal["queued", "running"]', Literal["failed"]]""",
        """Annotated['Literal["queued", "running", "failed"]', "note"]""",
    ],
)
def test_postponed_field_annotations_are_discovered(gate, annotation: str) -> None:
    source = f"""import typing as t
from typing import Literal, Optional, Union, Annotated
class Job:
    status: {annotation.strip()}
"""
    found = gate.work_state_literals(source, "pkg.worker")
    assert found == {"pkg.worker::Job.status": STATES}
    assert gate.audit({"lifecycles": {}}, found)


@pytest.mark.parametrize(
    "annotation",
    ["'RunStatus'", "Optional['RunStatus']", "'Optional[RunStatus]'"],
)
def test_quoted_reuse_keeps_the_named_vocabulary_identity(gate, annotation: str) -> None:
    source = f"""from typing import Literal, Optional
RunStatus = Literal["queued", "running", "failed"]
class Job:
    status: {annotation}
"""
    assert gate.work_state_literals(source, "pkg.worker") == {"pkg.worker::RunStatus": STATES}


def test_quoted_imported_extension_still_requires_a_disposition(gate) -> None:
    source = """from typing import Literal
from .base import RunStatus
class Job:
    status: 'RunStatus | Literal["cancelled"]'
"""
    assert gate.work_state_literals(source, "pkg.worker") == {
        "pkg.worker::Job.status": {"CANCELLED", "<imported-type:.base.RunStatus>"},
    }


@pytest.mark.parametrize(
    "annotation",
    [
        "'not valid ['",
        "'int'",
        """Annotated[str, 'Literal["queued", "running", "failed"]']""",
        """Literal['Literal["queued", "running", "failed"]']""",
        """'__import__("module_that_must_never_be_executed").run()'""",
    ],
)
def test_quoted_annotations_never_execute_or_reinterpret_metadata(gate, annotation: str) -> None:
    source = f"""from typing import Literal, Annotated
class Job:
    status: {annotation.strip()}
"""
    assert gate.work_state_literals(source, "pkg.worker") == {}


def test_postponed_alias_cycles_are_bounded(gate) -> None:
    source = """from typing import Optional
_Helper = Optional["_Helper"]
class Job:
    status: "_Helper"
"""
    assert gate.work_state_literals(source, "pkg.worker") == {}


def test_a_runtime_string_assignment_is_not_a_type_alias(gate) -> None:
    source = """RunStatus = 'Literal["queued", "running", "failed"]'\n"""
    assert gate.work_state_literals(source, "pkg.worker") == {}
