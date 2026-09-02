"""Focused branch coverage for the M1 convergence-freeze checker."""

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
    spec = importlib.util.spec_from_file_location("m1_convergence_freeze_branch_coverage", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _policy() -> dict[str, object]:
    return json.loads(POLICY.read_text(encoding="utf-8"))


def _ontology() -> dict[str, object]:
    return json.loads(ONTOLOGY.read_text(encoding="utf-8"))


def test_unrelated_new_class_is_not_treated_as_a_shared_owner() -> None:
    checker = _module()

    assert (
        checker.new_shared_owner_violations(
            "class LocalWidget:\n    pass\n",
            "",
            module="product.local",
            policy=_policy(),
            ontology=_ontology(),
        )
        == []
    )


def test_authoritative_gate_map_fails_closed_when_missing() -> None:
    checker = _module()

    assert checker.validate_authoritative_gate_map({}) == [
        "freeze policy has no authoritative_gates object"
    ]


def test_authoritative_gate_map_reports_a_wrong_mapping() -> None:
    checker = _module()
    policy = _policy()
    gates = dict(policy["authoritative_gates"])
    gates["model_egress"] = "scripts/not-the-authoritative-gate.py"
    policy["authoritative_gates"] = gates

    failures = checker.validate_authoritative_gate_map(policy)

    assert any("authoritative_gates.model_egress" in failure for failure in failures)


def test_production_python_filter_and_module_names() -> None:
    checker = _module()

    assert checker._is_production_python("packages/example/src/example/service.py")
    assert checker._is_production_python("packages/hive-conductor/backend/routes/runs.py")
    assert not checker._is_production_python("packages/example/tests/test_service.py")
    assert not checker._is_production_python("docs/example.py")
    assert checker._module_name("packages/example/src/example/service.py") == "example.service"
    assert (
        checker._module_name("packages/hive-conductor/backend/routes/runs.py")
        == "packages.hive-conductor.backend.routes.runs"
    )


def test_changed_python_pairs_handles_modified_added_renamed_and_irrelevant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = _module()
    result = SimpleNamespace(
        returncode=0,
        stderr="",
        stdout="\n".join(
            (
                "M\tpackages/example/src/example/modified.py",
                "A\tpackages/example/src/example/added.py",
                "R100\tpackages/example/src/example/old.py\tpackages/example/src/example/new.py",
                "D\tpackages/example/src/example/deleted.py",
                "M\tdocs/not-production.py",
            )
        ),
    )
    monkeypatch.setattr(checker.subprocess, "run", lambda *_args, **_kwargs: result)

    assert checker._changed_python_pairs("base") == [
        (
            "packages/example/src/example/modified.py",
            "packages/example/src/example/modified.py",
        ),
        (None, "packages/example/src/example/added.py"),
        (
            "packages/example/src/example/old.py",
            "packages/example/src/example/new.py",
        ),
    ]


def test_changed_python_pairs_surfaces_git_diff_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    checker = _module()
    result = SimpleNamespace(returncode=1, stderr="bad revision", stdout="")
    monkeypatch.setattr(checker.subprocess, "run", lambda *_args, **_kwargs: result)

    with pytest.raises(RuntimeError, match="bad revision"):
        checker._changed_python_pairs("missing-base")


def test_exception_plan_prefers_explicit_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    checker = _module()
    monkeypatch.setenv("M1_CONVERGENCE_EXCEPTION_PLAN", "reviewed plan")
    monkeypatch.setenv("GITHUB_EVENT_PATH", "/definitely/not/read.json")

    assert checker._exception_plan_from_environment() == "reviewed plan"


def test_exception_plan_fails_closed_for_malformed_event(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checker = _module()
    event = tmp_path / "event.json"
    event.write_text("{not json", encoding="utf-8")
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
