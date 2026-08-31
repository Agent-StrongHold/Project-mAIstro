"""Regression tests for trusted public-route provenance in shallow CI (#542)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


class _FakeProvenanceError(RuntimeError):
    pass


def _load_public_routes() -> ModuleType:
    path = ROOT / "scripts" / "check-public-routes.py"
    name = "_m1_542_public_routes_shallow_ci"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _result(args: list[str], returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["git", *args], returncode, stdout, stderr)


def test_shallow_pull_request_materializes_event_ref_and_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_routes = _load_public_routes()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REF", "refs/pull/721/merge")
    provenance = SimpleNamespace(
        _github_event_base=lambda: "origin/develop",
        RatchetProvenanceError=_FakeProvenanceError,
    )
    calls: list[list[str]] = []

    def fake_git(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args == ["rev-parse", "--is-shallow-repository"]:
            return _result(args, stdout="true\n")
        return _result(args)

    monkeypatch.setattr(public_routes, "_run_git", fake_git)

    public_routes._materialize_ci_history(provenance)

    assert calls == [
        ["rev-parse", "--is-shallow-repository"],
        ["fetch", "--no-tags", "--unshallow", "origin", "refs/pull/721/merge"],
        [
            "fetch",
            "--no-tags",
            "origin",
            "+refs/heads/develop:refs/remotes/origin/develop",
        ],
    ]


def test_shallow_pull_request_fetch_failure_is_not_downgraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_routes = _load_public_routes()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REF", "refs/pull/721/merge")
    provenance = SimpleNamespace(
        _github_event_base=lambda: "origin/develop",
        RatchetProvenanceError=_FakeProvenanceError,
    )

    def fake_git(args: list[str]) -> subprocess.CompletedProcess[str]:
        if args == ["rev-parse", "--is-shallow-repository"]:
            return _result(args, stdout="true\n")
        return _result(args, returncode=1, stderr="network unavailable")

    monkeypatch.setattr(public_routes, "_run_git", fake_git)

    with pytest.raises(_FakeProvenanceError, match="could not unshallow GitHub event ref"):
        public_routes._materialize_ci_history(provenance)
