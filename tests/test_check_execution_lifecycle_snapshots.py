"""Definition-time bindings cannot be rewritten by later source (#1136)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATES = {"QUEUED", "RUNNING", "FAILED"}
LITERAL = 'Literal["queued", "running", "failed"]'


@pytest.fixture(scope="module")
def gate():
    path = Path(
        os.environ.get("LIFECYCLE_GATE_UNDER_TEST", ROOT / "scripts/check-execution-lifecycles.py")
    )
    spec = importlib.util.spec_from_file_location("_lifecycle_snapshot_gate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("links", [0, 1, 3])
@pytest.mark.parametrize("replacement", ["str", 'Literal["red", "green", "blue"]'])
def test_transitive_aliases_keep_their_definition_time_helpers(gate, links, replacement) -> None:
    source = f"from typing import Literal\nValues = {LITERAL}\n"
    name = "Values"
    for index in range(links):
        source += f"Copy{index} = {name}\n"
        name = f"Copy{index}"
    source += f"Saved = {name}\nValues = {replacement}\nRunStatus = Saved\n"
    assert gate.work_state_literals(source, "pkg.worker") == {"pkg.worker::RunStatus": STATES}


@pytest.mark.parametrize("links", [0, 1, 3])
def test_later_helpers_cannot_invent_an_earlier_alias(gate, links) -> None:
    source = "from typing import Literal\nValues = str\n"
    name = "Values"
    for index in range(links):
        source += f"Copy{index} = {name}\n"
        name = f"Copy{index}"
    source += f"Saved = {name}\nValues = {LITERAL}\nRunStatus = Saved\n"
    assert gate.work_state_literals(source, "pkg.worker") == {}


@pytest.mark.parametrize(
    "replacement",
    ["L = str", "from custom import Literal as L", "class L: pass", "def L(): pass"],
)
def test_a_later_typing_rebind_does_not_erase_an_existing_alias(gate, replacement) -> None:
    source = (
        'from typing import Literal as L\nRunStatus = L["queued", "running", "failed"]\n'
        f"{replacement}\n"
    )
    assert gate.work_state_literals(source, "pkg.worker") == {"pkg.worker::RunStatus": STATES}


def test_a_later_typing_import_does_not_reinterpret_an_earlier_custom_generic(gate) -> None:
    source = (
        'from custom import Literal as L\nRunStatus = L["queued", "running", "failed"]\n'
        "from typing import Literal as L\n"
    )
    assert gate.work_state_literals(source, "pkg.worker") == {}


@pytest.mark.parametrize("shadow", ["t = object", "import custom as t", "class t: pass"])
def test_qualified_typing_names_obey_their_module_binding(gate, shadow) -> None:
    source = f'import typing as t\n{shadow}\nRunStatus = t.Literal["queued", "running", "failed"]\n'
    assert gate.work_state_literals(source, "pkg.worker") == {}


def test_field_extension_uses_the_captured_alias_not_the_rebound_helper(gate) -> None:
    source = f"""from typing import Literal
class Worker:
    Values = {LITERAL}
    Status = Values
    Values = str
    status: Status | Literal["cancelled"]
"""
    assert gate.work_state_literals(source, "pkg.worker") == {
        "pkg.worker::Worker.Status": STATES,
        "pkg.worker::Worker.status": STATES | {"CANCELLED"},
    }


@pytest.mark.parametrize("child", ["class Inner:", "def make(self):", "async def make(self):"])
def test_class_imports_do_not_enter_child_lexical_scopes(gate, child) -> None:
    source = f"""from typing import Literal
from pkg.base import Status as Shared
class Outer:
    from unrelated import Status as Shared
    {child}
        RunStatus = Shared | Literal["cancelled"]
"""
    scope = "Inner" if child.startswith("class") else "make"
    assert gate.work_state_literals(source, "pkg.worker") == {
        f"pkg.worker::Outer.{scope}.RunStatus": {"CANCELLED", "<imported-type:pkg.base.Status>"}
    }


def test_class_typing_names_do_not_enter_a_nested_class(gate) -> None:
    source = """from custom import Literal as L
class Outer:
    from typing import Literal as L
    class Inner:
        RunStatus = L["queued", "running", "failed"]
"""
    assert gate.work_state_literals(source, "pkg.worker") == {}


@pytest.mark.parametrize(
    "expression",
    [
        'Literal["queued", "running"] | "Literal[\'failed\']"',
        '"Literal[\'queued\']" | Literal["running", "failed"]',
        'Optional[Literal["queued", "running"] | "Literal[\'failed\']"]',
    ],
)
def test_quoted_union_type_operands_are_discovered(gate, expression) -> None:
    source = f"from typing import Literal, Optional\nRunStatus = {expression}\n"
    assert gate.work_state_literals(source, "pkg.worker") == {"pkg.worker::RunStatus": STATES}


def test_quoted_union_reuse_does_not_duplicate_a_named_vocabulary(gate) -> None:
    source = f"""from typing import Literal
RunStatus = {LITERAL}
class Worker:
    status: Literal["queued"] | "RunStatus"
"""
    assert gate.work_state_literals(source, "pkg.worker") == {"pkg.worker::RunStatus": STATES}


@pytest.mark.parametrize("annotation", ["Final", "Final[str]", "str"])
def test_literal_constant_members_survive_later_rebinding(gate, annotation) -> None:
    source = f"""from typing import Literal, Final
QUEUED: {annotation} = "queued"
RUNNING: {annotation} = "running"
FAILED: {annotation} = "failed"
Saved = QUEUED
QUEUED = "red"
RunStatus = Literal[Saved, RUNNING, FAILED]
"""
    assert gate.work_state_literals(source, "pkg.worker") == {"pkg.worker::RunStatus": STATES}


def test_string_bindings_outside_literal_are_not_status_values(gate) -> None:
    source = """from typing import Union, Final
A: Final = "queued"
B: Final = "running"
C: Final = "failed"
RunStatus = Union[A, B, C]
"""
    assert gate.work_state_literals(source, "pkg.worker") == {}


@pytest.mark.parametrize("shape", ["alias", "field"])
def test_stage_names_share_the_existing_vocabulary_filter(gate, shape) -> None:
    declaration = (
        f"ExecutionStage = {LITERAL}" if shape == "alias" else f"class Job:\n    stage: {LITERAL}"
    )
    name = "ExecutionStage" if shape == "alias" else "Job.stage"
    assert gate.work_state_literals("from typing import Literal\n" + declaration, "pkg.worker") == {
        f"pkg.worker::{name}": STATES
    }
    assert (
        gate.work_state_literals(
            'from typing import Literal\nExecutionStage = Literal["seed", "flower", "fruit"]',
            "pkg.garden",
        )
        == {}
    )


@pytest.mark.parametrize(
    "declarations",
    [
        f"type RunStatus = Values\nValues = {LITERAL}",
        f"Values = str\ntype RunStatus = Values\nValues = {LITERAL}",
        f"type Deferred = Values\nRunStatus = Deferred\nValues = {LITERAL}",
    ],
)
def test_pep695_aliases_retain_their_explicitly_lazy_scope(gate, declarations) -> None:
    source = f"from typing import Literal\n{declarations}\n"
    assert gate.work_state_literals(source, "pkg.worker") == {"pkg.worker::RunStatus": STATES}


def test_class_local_pep695_annotation_scope_still_sees_class_values(gate) -> None:
    source = f"""from typing import Literal
Values = str
class Worker:
    type RunStatus = Values
    Values = {LITERAL}
"""
    assert gate.work_state_literals(source, "pkg.worker") == {
        "pkg.worker::Worker.RunStatus": STATES
    }


def test_a_transitive_snapshot_cannot_self_authorize_at_the_trusted_base(
    gate, tmp_path, monkeypatch
) -> None:
    """Run the real scanner over separate Git revisions, without fabricated evidence."""
    source = tmp_path / "worker.py"
    original = f"from typing import Literal\nValues = {LITERAL}\nSaved = Values\nValues = str\n"
    source.write_text(original)
    for arguments in (
        ["init", "-q"],
        ["add", "worker.py"],
        [
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "base",
        ],
    ):
        subprocess.run(["git", "-C", str(tmp_path), *arguments], check=True)
    revision = subprocess.check_output(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True
    ).strip()
    source.write_text(original + "RunStatus = Saved\n")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(
        gate,
        "_load_reachability",
        lambda: SimpleNamespace(
            FLAT_APPS=(),
            _collect_modules=lambda: {"pkg.worker": source},
            _display_name=lambda name, _apps: name,
        ),
    )
    found = gate.work_state_literals(source.read_text(), "pkg.worker")
    assert found == {"pkg.worker::RunStatus": STATES}
    visible = gate._discover_at_revision(revision, found)
    assert visible == set()
    assert gate._unauthorized_additions(list(found), {}, visible) == ["pkg.worker::RunStatus"]
    assert gate.audit({"lifecycles": {}}, found)


@pytest.mark.parametrize(
    ("imports", "copy", "expression", "shadow"),
    [
        (
            "from typing import Literal as L",
            "Saved = L",
            'Saved["queued", "running", "failed"]',
            "L = str",
        ),
        (
            "import typing as t",
            "Saved = t",
            'Saved.Literal["queued", "running", "failed"]',
            "t = object",
        ),
    ],
)
def test_copied_typing_forms_keep_the_original_import(
    gate, imports, copy, expression, shadow
) -> None:
    source = f"{imports}\n{copy}\n{shadow}\nRunStatus = {expression}\n"
    assert gate.work_state_literals(source, "pkg.worker") == {"pkg.worker::RunStatus": STATES}
