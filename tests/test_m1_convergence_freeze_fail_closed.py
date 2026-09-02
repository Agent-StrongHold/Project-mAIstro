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


def _stub_main_dependencies(
    checker: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    *,
    gate_failures: list[str],
    freeze_failures: list[str],
    owner_failures: list[str],
) -> None:
    args = SimpleNamespace(base="base-sha", exception=False)
    parser = SimpleNamespace(parse_args=lambda: args)
    monkeypatch.setattr(checker, "build_parser", lambda: parser)
    monkeypatch.setattr(checker, "_policy", lambda: {})
    monkeypatch.setattr(checker, "_ontology", lambda: {})
    monkeypatch.setattr(checker, "validate_authoritative_gate_map", lambda _policy: gate_failures)
    monkeypatch.setattr(checker, "_git_show", lambda _base, _path: "base matrix")
    monkeypatch.setattr(checker, "check", lambda *_args, **_kwargs: freeze_failures)
    monkeypatch.setattr(
        checker,
        "shared_owner_failures",
        lambda *_args, **_kwargs: owner_failures,
    )


def test_main_reports_all_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    checker = _module()
    _stub_main_dependencies(
        checker,
        monkeypatch,
        gate_failures=["bad gate"],
        freeze_failures=["bad freeze"],
        owner_failures=["bad owner"],
    )

    assert checker.main() == 1
    assert capsys.readouterr().out.splitlines() == [
        "ERROR: bad gate",
        "ERROR: bad freeze",
        "ERROR: bad owner",
    ]


def test_main_reports_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    checker = _module()
    _stub_main_dependencies(
        checker,
        monkeypatch,
        gate_failures=[],
        freeze_failures=[],
        owner_failures=[],
    )

    assert checker.main() == 0
    output = capsys.readouterr().out
    assert output == "M1 convergence freeze: no unapproved new architecture island\n"
