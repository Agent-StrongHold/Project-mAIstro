"""Fail-closed coverage for the M1 convergence-freeze checker (#460)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check-m1-convergence-freeze.py"
POLICY = ROOT / "quality" / "m1-convergence-freeze.json"
ONTOLOGY = ROOT / "quality" / "shared-interop-ontology-v1.json"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("m1_convergence_freeze_fail_closed", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _policy() -> dict[str, object]:
    return json.loads(POLICY.read_text(encoding="utf-8"))


def _ontology() -> dict[str, object]:
    return json.loads(ONTOLOGY.read_text(encoding="utf-8"))


def test_ownership_matrix_requires_marker_and_rows() -> None:
    checker = _module()

    with pytest.raises(ValueError, match="missing"):
        checker._subsystems("# no ownership marker")

    with pytest.raises(ValueError, match="no subsystem rows"):
        checker._subsystems("<!-- matrix:ownership -->\n| Subsystem | Modules |\n|---|---|\n")


def test_exception_policy_schema_fails_closed() -> None:
    checker = _module()

    with pytest.raises(ValueError, match="no exception_policy"):
        checker._required_plan_fields({})

    with pytest.raises(ValueError, match="required_plan_fields"):
        checker._required_plan_fields({"exception_policy": {}})


def test_invalid_python_source_has_no_class_records() -> None:
    checker = _module()

    assert checker._class_records("class broken(") == {}


def test_ontology_schema_fails_closed() -> None:
    checker = _module()
    policy = _policy()

    with pytest.raises(ValueError, match="no concepts object"):
        checker._canonical_owner_map(policy, {})

    with pytest.raises(ValueError, match="has no owner"):
        checker._canonical_owner_map(policy, {"concepts": {"Run": {}}})

    bad_supplemental = dict(policy)
    bad_supplemental["supplemental_shared_owners"] = []
    with pytest.raises(ValueError, match="must be an object"):
        checker._canonical_owner_map(bad_supplemental, _ontology())

    empty_owner = dict(policy)
    empty_owner["supplemental_shared_owners"] = {"Checkpoint": []}
    with pytest.raises(ValueError, match="needs owner prefixes"):
        checker._canonical_owner_map(empty_owner, _ontology())


def test_changed_python_pairs_parses_supported_statuses(monkeypatch: pytest.MonkeyPatch) -> None:
    checker = _module()
    output = "\n".join(
        (
            "A\tpackages/example/src/example/new.py",
            "M\tpackages/example/src/example/changed.py",
            "R100\tpackages/example/src/example/old.py\tpackages/example/src/example/moved.py",
            "A\tpackages/example/tests/test_new.py",
            "D\tpackages/example/src/example/deleted.py",
            "M\tdocs/not-python.md",
        )
    )
    result = SimpleNamespace(returncode=0, stdout=output, stderr="")
    monkeypatch.setattr(checker.subprocess, "run", lambda *_args, **_kwargs: result)

    assert checker._changed_python_pairs("base") == [
        (None, "packages/example/src/example/new.py"),
        ("packages/example/src/example/changed.py", "packages/example/src/example/changed.py"),
        ("packages/example/src/example/old.py", "packages/example/src/example/moved.py"),
    ]


def test_changed_python_pairs_reports_git_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    checker = _module()
    result = SimpleNamespace(returncode=1, stdout="", stderr="bad revision")
    monkeypatch.setattr(checker.subprocess, "run", lambda *_args, **_kwargs: result)

    with pytest.raises(RuntimeError, match="cannot diff production files"):
        checker._changed_python_pairs("missing")


def test_exception_plan_prefers_explicit_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    checker = _module()
    monkeypatch.setenv("M1_CONVERGENCE_EXCEPTION_PLAN", " reviewed plan ")
    monkeypatch.setenv("GITHUB_EVENT_PATH", "/does/not/matter")

    assert checker._exception_plan_from_environment() == " reviewed plan "


def test_exception_plan_without_event_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    checker = _module()
    monkeypatch.delenv("M1_CONVERGENCE_EXCEPTION_PLAN", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)

    assert checker._exception_plan_from_environment() == ""


def test_exception_plan_malformed_event_is_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checker = _module()
    event = tmp_path / "event.json"
    event.write_text("{not-json", encoding="utf-8")
    monkeypatch.delenv("M1_CONVERGENCE_EXCEPTION_PLAN", raising=False)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))

    assert checker._exception_plan_from_environment() == ""


def test_exception_plan_requires_pull_request_object(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checker = _module()
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": "not-an-object"}), encoding="utf-8")
    monkeypatch.delenv("M1_CONVERGENCE_EXCEPTION_PLAN", raising=False)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))

    assert checker._exception_plan_from_environment() == ""


def test_exception_plan_reads_pull_request_body(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checker = _module()
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"body": "reviewed body"}}), encoding="utf-8")
    monkeypatch.delenv("M1_CONVERGENCE_EXCEPTION_PLAN", raising=False)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))

    assert checker._exception_plan_from_environment() == "reviewed body"
