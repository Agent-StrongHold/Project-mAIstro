"""Tests for the principal-identity ratchet (Workspace cutover P0.1)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-principal-identity.py"
BASELINE = ROOT / "quality" / "principal-identity-baseline.json"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_principal_identity", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_baseline_matches_current_violations(gate) -> None:
    violations = gate.collect_violations()
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))["tolerated"]
    current = {item.key(): item.detail for item in violations}
    assert set(baseline) == set(current)


def test_no_new_violations(gate) -> None:
    new_violations, stale_keys, _ = gate.audit()
    assert not new_violations
    assert not stale_keys


class _FakeBaselineRef:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def loads(self, default: object = None) -> object:
        return self._payload if self._payload is not None else default


def _stub_provenance(payload: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        RatchetProvenanceError=type("RatchetProvenanceError", (RuntimeError,), {}),
        resolve_baseline=lambda path, root=None: _FakeBaselineRef(payload),
    )


def test_audit_judges_new_violations_against_trusted_base(
    gate, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NEW is judged against the merge-base ledger, not the worktree copy.

    A candidate that writes a violation and the baseline row blessing it in
    the same change must not approve its own regression (#542, #319).
    """
    monkeypatch.setattr(gate, "_provenance", lambda: _stub_provenance({"tolerated": {}}))
    new_violations, _, _ = gate.audit()
    assert new_violations, "current violations must read as NEW against an empty trusted base"


def test_audit_prunes_stale_rows_against_candidate_ledger(
    gate, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = {item.key(): item.detail for item in gate.collect_violations()}
    monkeypatch.setattr(gate, "_provenance", lambda: _stub_provenance({"tolerated": dict(current)}))
    monkeypatch.setattr(gate, "_load_baseline", lambda: {**current, "ghost::p:1:d": "gone"})
    new_violations, stale_keys, _ = gate.audit()
    assert not new_violations
    assert "ghost::p:1:d" in stale_keys
