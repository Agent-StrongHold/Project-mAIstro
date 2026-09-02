"""Focused branch coverage for the M1 convergence-freeze checker."""

from __future__ import annotations

import importlib.util
import json
import sys
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


class _Prov:
    """Provenance stand-in whose resolver yields the given text."""

    def __init__(self, text: str | None) -> None:
        self._text = text

    def resolve_baseline(self, path, root=None):
        return SimpleNamespace(text=self._text)


def test_provenance_returns_cached_module(monkeypatch: pytest.MonkeyPatch) -> None:
    checker = _module()
    cached = SimpleNamespace(cached=True)
    monkeypatch.setitem(sys.modules, "_ratchet_provenance", cached)

    assert checker._provenance() is cached


def test_provenance_rejects_unloadable_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    checker = _module()
    monkeypatch.setattr(importlib.util, "spec_from_file_location", lambda *a, **k: None)

    with pytest.raises(RuntimeError, match="cannot load"):
        checker._provenance()


def test_provenance_cleans_sys_modules_on_exec_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    checker = _module()
    boom = importlib.util.spec_from_file_location("_ratchet_provenance", checker._PROVENANCE_SOURCE)
    assert boom is not None

    class _BoomLoader:
        def create_module(self, spec) -> None:
            return None

        def exec_module(self, module: ModuleType) -> None:
            raise RuntimeError("loader exploded")

    boom.loader = _BoomLoader()
    monkeypatch.setattr(importlib.util, "spec_from_file_location", lambda *a, **k: boom)
    monkeypatch.delitem(sys.modules, "_ratchet_provenance", raising=False)

    with pytest.raises(RuntimeError, match="loader exploded"):
        checker._provenance()
    assert "_ratchet_provenance" not in sys.modules


def test_ontology_falls_back_to_empty_when_base_text_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = _module()
    monkeypatch.setattr(checker, "_provenance", lambda: _Prov(None))

    assert checker._ontology() == {}


def test_module_name_resolves_hive_conductor_path() -> None:
    checker = _module()

    name = checker._module_name("packages/hive-conductor/backend/services/dag_recovery.py")

    assert name == "packages.hive-conductor.backend.services.dag_recovery"


def _fake_completed(stdout: str = "", returncode: int = 0, **_unused) -> SimpleNamespace:
    return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)


def test_changed_python_pairs_classifies_rename_copy_add_and_skips() -> None:
    checker = _module()
    monkeypatch = pytest.MonkeyPatch()
    diff_output = (
        "R100\told/path/svc.py\tpackages/hive-conductor/backend/svc.py\n"
        "A\tpackages/hive-conductor/backend/new_test_target.py\n"
        "M\tpackages/maistro-core/src/maistro/mod.py\n"
        "D\tpackages/hive-conductor/backend/gone.py\n"
        "\tunrecognized row\n"
    )
    monkeypatch.setattr("subprocess.run", lambda *a, **k: _fake_completed(stdout=diff_output))
    try:
        pairs = checker._changed_python_pairs("base-sha")
    finally:
        monkeypatch.undo()

    assert pairs == [
        ("old/path/svc.py", "packages/hive-conductor/backend/svc.py"),
        (None, "packages/hive-conductor/backend/new_test_target.py"),
        ("packages/maistro-core/src/maistro/mod.py",) * 2,
    ]


def test_changed_python_pairs_raises_on_git_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    checker = _module()
    monkeypatch.setattr(
        "subprocess.run", lambda *a, **k: _fake_completed(returncode=128, stderr="boom")
    )

    with pytest.raises(RuntimeError, match="cannot diff production files"):
        checker._changed_python_pairs("base-sha")


def test_shared_owner_failures_tolerates_missing_base_blob(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = _module()
    existing = "packages/hive-conductor/backend/routes/dags.py"
    monkeypatch.setattr(checker, "_changed_python_pairs", lambda base: [(existing, existing)])
    monkeypatch.setattr("subprocess.run", lambda *a, **k: _fake_completed(returncode=1))
    monkeypatch.setattr(checker, "new_shared_owner_violations", lambda *a, **k: [])

    assert checker.shared_owner_failures("base", policy={}, ontology={}) == []
