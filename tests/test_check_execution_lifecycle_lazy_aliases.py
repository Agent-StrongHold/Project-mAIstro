"""Regression coverage for PEP 695 lazy alias environments (#1136)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast, get_args

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATES = {"QUEUED", "RUNNING", "FAILED"}
LITERAL = 'Literal["queued", "running", "failed"]'


@pytest.fixture(scope="module")
def gate() -> ModuleType:
    path = ROOT / "scripts/check-execution-lifecycles.py"
    spec = importlib.util.spec_from_file_location("_lifecycle_lazy_alias_gate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _native_states(source: str) -> set[str]:
    namespace: dict[str, object] = {}
    exec(compile(source, "<lazy-alias-fixture>", "exec"), namespace)

    def states(value: object) -> set[str]:
        try:
            while hasattr(value, "__value__"):
                value = cast(Any, value).__value__
        except Exception:
            return set()
        arguments = get_args(value)
        if arguments:
            return set().union(*(states(argument) for argument in arguments))
        return {value.upper()} if isinstance(value, str) else set()

    return states(namespace["Observed"])


def _assert_matches_native(gate: ModuleType, source: str, identity: str) -> None:
    native = _native_states(source)
    expected = {identity: native} if len(native & STATES) >= 3 else {}
    assert gate.work_state_literals(source, "fixture") == expected


@pytest.mark.parametrize(
    "declarations",
    [
        f"_Values = str\ntype RunStatus = _Values\n_Values = {LITERAL}",
        f"_Values = {LITERAL}\ntype RunStatus = _Values\n_Values = str",
        f"_Values = {LITERAL}\ntype RunStatus = _Values\n_Values = Literal['red', 'green', 'blue']",
        f"_Values = str\ntype RunStatus = _Values | None\n_Values = {LITERAL}",
        f"_Values = {LITERAL}\nRunStatus = _Values\n_Values = str",
        f"_Values = str\nRunStatus = _Values\n_Values = {LITERAL}",
        f"_Values = str\ntype Deferred = _Values\nRunStatus = Deferred\n_Values = {LITERAL}",
        f"_Values = {LITERAL}\ntype Deferred = _Values\n_Values = str\nRunStatus = Deferred",
        f"_Values = str\ntype Deferred = _Values\n_Values = {LITERAL}\ntype RunStatus = Deferred",
    ],
)
def test_module_binding_order_matches_native_python(gate: ModuleType, declarations: str) -> None:
    source = f"from typing import Literal\n{declarations}\nObserved = RunStatus\n"
    _assert_matches_native(gate, source, "fixture::RunStatus")


@pytest.mark.parametrize(
    "declarations",
    [
        f"_Values = str\nclass Job:\n    type RunStatus = _Values\n_Values = {LITERAL}",
        f"_Values = {LITERAL}\nclass Job:\n    type RunStatus = _Values\n_Values = str",
        f"_Values = {LITERAL}\nclass Job:\n    RunStatus = _Values\n_Values = str",
    ],
)
def test_enclosing_function_binding_order_matches_native_python(
    gate: ModuleType, declarations: str
) -> None:
    source = f"""from typing import Literal
def build():
    {declarations.replace(chr(10), chr(10) + "    ")}
    return Job.RunStatus
Observed = build()
"""
    _assert_matches_native(gate, source, "fixture::build.Job.RunStatus")


@pytest.mark.parametrize(
    "declarations",
    [
        'from typing import Literal as L\ntype RunStatus = L["queued", "running", "failed"]\nL = str',
        'from typing import Literal as L\nRunStatus = L["queued", "running", "failed"]\nL = str',
        'from typing import Literal as L\ntype RunStatus = L["queued", "running", "failed"]\nfrom typing import Literal as L',
        "import typing as t\nimport typing\ntype RunStatus = t.Literal['queued', 'running', 'failed']\nt = typing",
    ],
)
def test_typing_import_rebinding_matches_native_python(gate: ModuleType, declarations: str) -> None:
    source = f"{declarations}\nObserved = RunStatus\n"
    _assert_matches_native(gate, source, "fixture::RunStatus")


@pytest.mark.parametrize(
    "declarations",
    [
        f"_Values = {LITERAL}\nclass Outer:\n    _Values = str\n    class Inner:\n        type RunStatus = _Values",
        f"_Values = str\nclass Outer:\n    _Values = {LITERAL}\n    class Inner:\n        type RunStatus = _Values",
    ],
)
def test_nested_class_lookup_skips_outer_class_namespace(
    gate: ModuleType, declarations: str
) -> None:
    source = f"from typing import Literal\n{declarations}\nObserved = Outer.Inner.RunStatus\n"
    _assert_matches_native(gate, source, "fixture::Outer.Inner.RunStatus")


@pytest.mark.parametrize(
    "declarations",
    [
        f"_Values = {LITERAL}\nRunStatus = _Values\n_Values = str",
        f"_Values = str\nRunStatus = _Values\n_Values = {LITERAL}",
        f"_Values = {LITERAL}\nSaved = _Values\n_Values = str\nRunStatus = Saved",
        f"_Values = str\nSaved = _Values\n_Values = {LITERAL}\nRunStatus = Saved",
    ],
)
def test_eager_aliases_keep_definition_time_bindings(gate: ModuleType, declarations: str) -> None:
    source = f"from typing import Literal\n{declarations}\nObserved = RunStatus\n"
    _assert_matches_native(gate, source, "fixture::RunStatus")


def _git_revision(tmp_path: Path, source: str) -> str:
    path = tmp_path / "worker.py"
    path.write_text(source, encoding="utf-8")
    for args in (
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
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True)
    return subprocess.check_output(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True
    ).strip()


@pytest.mark.parametrize(
    ("base", "candidate", "expected"),
    [
        (
            "from typing import Literal\n_Values = str\n",
            f"from typing import Literal\n_Values = str\nclass Job:\n    type RunStatus = _Values\n_Values = {LITERAL}\n",
            set(),
        ),
        (
            f"from typing import Literal\nRunStatus = {LITERAL}\n",
            f"from typing import Literal\nRunStatus = {LITERAL}\nclass Job:\n    type RunStatus = str\n",
            {"fixture::RunStatus"},
        ),
    ],
)
def test_real_git_revisions_bound_trusted_visibility(
    gate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    base: str,
    candidate: str,
    expected: set[str],
) -> None:
    revision = _git_revision(tmp_path, base)
    source = tmp_path / "worker.py"
    source.write_text(candidate, encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(
        gate,
        "_load_reachability",
        lambda: type(
            "Reachability",
            (),
            {
                "FLAT_APPS": (),
                "_collect_modules": staticmethod(lambda: {"fixture::worker": source}),
                "_display_name": staticmethod(lambda name, _apps: "fixture"),
            },
        )(),
    )
    found = gate.work_state_literals(candidate, "fixture")
    assert gate._discover_at_revision(revision, found) == expected
