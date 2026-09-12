"""Regression evidence for #1136's scoped Literal discovery and trusted-base lookup."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-execution-lifecycles.py"
STATES = {"QUEUED", "RUNNING", "FAILED"}


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("lifecycle_review_gate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_same_named_aliases_have_distinct_lexical_identities(gate) -> None:
    source = """
from typing import Literal
class A:
    Status = Literal["queued", "running", "failed"]
class B:
    Status = Literal["queued", "running", "failed"]
def make_a():
    Status = Literal["queued", "running", "failed"]
def make_b():
    Status = Literal["queued", "running", "failed"]
class Outer:
    class Inner:
        type Status = Literal["queued", "running", "failed"]
"""
    assert gate.work_state_literals(source, "pkg.jobs") == {
        f"pkg.jobs::{scope}.Status": STATES
        for scope in ("A", "B", "make_a", "make_b", "Outer.Inner")
    }


def test_sibling_helpers_do_not_overwrite_each_other(gate) -> None:
    source = """
from typing import Literal
class A:
    _Values = Literal["queued", "running", "failed"]
    State = _Values
class B:
    _Values = Literal["red", "green", "blue"]
    State = _Values
"""
    assert gate.work_state_literals(source, "pkg.jobs") == {"pkg.jobs::A.State": STATES}


def test_parent_alias_is_resolved_before_a_child_shadows_its_helper(gate) -> None:
    source = """
from typing import Literal
_Values = Literal["queued", "running", "failed"]
ParentStatus = _Values
class Child:
    _Values = Literal["red", "green", "blue"]
    ChildStatus = ParentStatus
"""
    assert gate.work_state_literals(source, "pkg.jobs") == {
        "pkg.jobs::ParentStatus": STATES,
        "pkg.jobs::Child.ChildStatus": STATES,
    }


def test_nested_fields_preserve_the_enclosing_class_identity(gate) -> None:
    source = """
from typing import Literal
class A:
    class Job:
        status: Literal["queued", "running", "failed"]
class B:
    class Job:
        status: Literal["queued", "running", "failed"]
"""
    assert gate.work_state_literals(source, "pkg.jobs") == {
        "pkg.jobs::A.Job.status": STATES,
        "pkg.jobs::B.Job.status": STATES,
    }


@pytest.mark.parametrize(
    "annotation",
    [
        'Optional[Literal["queued", "running", "failed"]]',
        'Union[Literal["queued", "running"], Literal["failed"], None]',
        'Annotated[Literal["queued", "running", "failed"], "metadata"]',
        't.Optional[t.Annotated[L["queued", "running", "failed"], "metadata"]]',
        'Maybe[Tagged[Either[L["queued", "running"], L["failed"]], "metadata"]]',
        't.Union[L["queued", "running", "failed"], None] | None',
    ],
)
def test_wrapped_aliases_and_fields_are_discovered(gate, annotation: str) -> None:
    imports = """
import typing as t
from typing import Literal, Optional, Union, Annotated
from typing_extensions import Literal as L, Optional as Maybe, Annotated as Tagged, Union as Either
"""
    assert gate.work_state_literals(imports + f"RunStatus = {annotation}\n", "pkg.jobs") == {
        "pkg.jobs::RunStatus": STATES,
    }
    assert gate.work_state_literals(
        imports + f"class Job:\n    status: {annotation}\n", "pkg.jobs"
    ) == {"pkg.jobs::Job.status": STATES}


def test_annotated_metadata_does_not_invent_a_lifecycle(gate) -> None:
    source = """
from typing import Annotated, Literal
RunStatus = Annotated[str, Literal["queued", "running", "failed"]]
class Job:
    status: Annotated[str, "queued", "running", "failed"]
"""
    assert gate.work_state_literals(source, "pkg.jobs") == {}


def test_annotated_metadata_does_not_suppress_an_independent_field(gate) -> None:
    source = """
from typing import Annotated, Literal
RunStatus = Literal["queued", "running", "failed"]
class Job:
    status: Annotated[Literal["queued", "running", "failed"], RunStatus]
"""
    assert gate.work_state_literals(source, "pkg.jobs") == {
        "pkg.jobs::RunStatus": STATES,
        "pkg.jobs::Job.status": STATES,
    }


def test_wrapping_a_named_alias_reuses_its_identity(gate) -> None:
    source = """
from typing import Annotated, Literal, Optional
RunStatus = Literal["queued", "running", "failed"]
class Job:
    status: Annotated[Optional[RunStatus], "metadata"]
"""
    assert gate.work_state_literals(source, "pkg.jobs") == {"pkg.jobs::RunStatus": STATES}


def test_a_field_extending_a_named_alias_remains_visible(gate) -> None:
    source = """
from typing import Literal
RunStatus = Literal["queued", "running", "failed"]
class Job:
    status: RunStatus | Literal["cancelled"]
"""
    assert gate.work_state_literals(source, "pkg.jobs") == {
        "pkg.jobs::RunStatus": STATES,
        "pkg.jobs::Job.status": STATES | {"CANCELLED"},
    }


def test_recursive_aliases_terminate_without_inventing_values(gate) -> None:
    assert gate.work_state_literals("A = B\nB = A\nRunStatus = A\n", "pkg.jobs") == {}


def test_a_new_sibling_cannot_use_an_existing_scope_disposition(gate) -> None:
    base = (
        'from typing import Literal\nclass A:\n'
        '    Status = Literal["queued", "running", "failed"]\n'
    )
    candidate = base + 'class B:\n    Status = Literal["queued", "running", "failed"]\n'
    trusted = gate.work_state_literals(base, "pkg.jobs")
    found = gate.work_state_literals(candidate, "pkg.jobs")
    entries = {name: {"classification": "DOMAIN", "rationale": "existing"} for name in trusted}
    failures = gate.audit({"lifecycles": entries}, found)
    assert any(
        "pkg.jobs::B.Status" in failure and "unclassified" in failure for failure in failures
    )
    assert gate._unauthorized_additions(sorted(set(found) - set(trusted)), {}, set(trusted)) == [
        "pkg.jobs::B.Status",
    ]


@pytest.mark.parametrize(
    "module", ["maistro-turing-backend::models", "other-app::models", "pkg.models"]
)
def test_trusted_revision_lookup_preserves_prefixed_module_names(
    gate, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, module: str
) -> None:
    """Use real git history: candidate-only aliases must not become trusted evidence."""
    source = tmp_path / "models.py"
    source.write_text(
        'from typing import Literal\nRunStatus = Literal["queued", "running", "failed"]\n'
    )
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "models.py"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "trusted source",
        ],
        check=True,
    )
    result = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    revision = result.stdout.strip()
    source.write_text(source.read_text() + 'NewStatus = Literal["pending", "running", "failed"]\n')
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    reachability = SimpleNamespace(
        FLAT_APPS=(),
        _collect_modules=lambda: {"fixture": source},
        _display_name=lambda *_args: module,
    )
    monkeypatch.setattr(gate, "_load_reachability", lambda: reachability)
    current = gate.work_state_literals(source.read_text(), module)
    assert gate._discover_at_revision(revision, current) == {f"{module}::RunStatus"}
    assert gate._unauthorized_additions(
        sorted(current), {}, gate._discover_at_revision(revision, current)
    ) == [f"{module}::NewStatus"]
