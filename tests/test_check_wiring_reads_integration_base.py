"""Regression tests for wiring-ratchet base selection on long-lived PRs (#727)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-wiring-reads.py"


@pytest.fixture
def check():
    spec = importlib.util.spec_from_file_location("check_wiring_reads_integration_base", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Baseline:
    base_sha = "b" * 40

    def loads(self, default=None):
        return {"metric_definition_version": "1", "roots": {}}


class _Provenance:
    BASE_REV_ENV = "RATCHET_BASE_REV"

    class RatchetProvenanceError(RuntimeError):
        pass

    def __init__(self):
        self.base = object()

    def resolve_baseline(self, _path, *, base=None, root=None):
        self.base = base
        return _Baseline()


def test_pull_request_uses_current_integration_target_not_historical_base_sha(
    check, monkeypatch
):
    """A long-lived PR must not inherit debt that landed later on its target branch."""
    prov = _Provenance()
    monkeypatch.setattr(check, "_provenance", lambda: prov)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_BASE_REF", "develop")
    monkeypatch.setenv("RATCHET_BASE_REV", "a" * 40)

    check._trusted_baseline()

    assert prov.base == "origin/develop"


def test_pull_request_without_explicit_ratchet_base_keeps_local_fallback_semantics(
    check, monkeypatch
):
    """Root/shallow test jobs that never opted into a CI base stay usable."""
    prov = _Provenance()
    monkeypatch.setattr(check, "_provenance", lambda: prov)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_BASE_REF", "develop")
    monkeypatch.delenv("RATCHET_BASE_REV", raising=False)

    check._trusted_baseline()

    assert prov.base is None


def test_non_pr_events_preserve_the_explicit_event_revision(check, monkeypatch):
    """Push/merge-group callers remain bound by the revision their workflow supplies."""
    prov = _Provenance()
    monkeypatch.setattr(check, "_provenance", lambda: prov)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "merge_group")
    monkeypatch.setenv("GITHUB_BASE_REF", "develop")
    monkeypatch.setenv("RATCHET_BASE_REV", "c" * 40)

    check._trusted_baseline()

    # None means resolve_baseline still consumes RATCHET_BASE_REV itself.
    assert prov.base is None
