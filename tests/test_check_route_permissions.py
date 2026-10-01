"""Tests for the authenticated route-permission ratchet (Workspace cutover P0.2)."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-route-permissions.py"
BASELINE = ROOT / "quality" / "route-permissions-baseline.json"
REGISTRY = ROOT / "quality" / "route-permissions.json"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_route_permissions", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_baseline_matches_current_gaps(gate) -> None:
    gaps, import_error = gate.collect_gaps()
    assert import_error is None, import_error
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))["tolerated"]
    current = {item.key(): item.detail for item in gaps}
    assert set(baseline) == set(current)


def test_no_new_gaps(gate) -> None:
    new_gaps, stale_keys, _, import_error = gate.audit()
    assert import_error is None, import_error
    assert not new_gaps
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


def test_audit_judges_new_gaps_against_trusted_base(gate, monkeypatch: pytest.MonkeyPatch) -> None:
    """NEW is judged against the merge-base ledger, not the worktree copy.

    A candidate that writes a gap and the baseline row blessing it in the
    same change must not approve its own regression (#542, #319).
    """
    monkeypatch.setattr(gate, "_provenance", lambda: _stub_provenance({"tolerated": {}}))
    new_gaps, _, _, import_error = gate.audit()
    assert import_error is None, import_error
    assert new_gaps, "current gaps must read as NEW against an empty trusted base"


def test_audit_prunes_stale_rows_against_candidate_ledger(
    gate, monkeypatch: pytest.MonkeyPatch
) -> None:
    gaps, import_error = gate.collect_gaps()
    assert import_error is None, import_error
    current = {item.key(): item.detail for item in gaps}
    monkeypatch.setattr(gate, "_provenance", lambda: _stub_provenance({"tolerated": dict(current)}))
    monkeypatch.setattr(gate, "_load_baseline", lambda: {**current, "ghost": "gone"})
    new_gaps, stale_keys, _, import_error = gate.audit()
    assert import_error is None, import_error
    assert not new_gaps
    assert "ghost" in stale_keys


def test_registry_entry_requires_permission_or_exempt(
    gate, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = tmp_path / "route-permissions.json"
    registry.write_text(
        json.dumps(
            {
                "prefixes": {
                    "/v1/example": {
                        "owner": "@someone",
                        "disposition": "permanent",
                        "reason": "because",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(gate, "REGISTRY", registry)
    problems = gate._entry_problems(
        "/v1/example", json.loads(registry.read_text())["prefixes"]["/v1/example"], date(2099, 1, 1)
    )
    assert problems


def test_registry_accepts_permission_entry(gate) -> None:
    entry = {
        "permission": "tasks.write",
        "owner": "@someone",
        "disposition": "permanent",
        "reason": "because",
    }
    assert not gate._entry_problems("/v1/tasks", entry, date.today())
