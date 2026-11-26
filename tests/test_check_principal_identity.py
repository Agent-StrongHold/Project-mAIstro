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
ROUTE = "packages/hive-conductor/backend/routes/x.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_principal_identity", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_dict_shaped_user_access_is_one_entry_per_file(gate) -> None:
    source = (
        "def handler(request):\n"
        "    a = request.state.user['id']\n"
        "    b = getattr(request.state, 'user', None)\n"
        "    setattr(request.state, 'user', {})\n"
    )
    [violation] = gate.scan_source(ROUTE, source)
    assert violation.key() == f"state_user_access::{ROUTE}"
    assert violation.detail.startswith("3 ")


def test_defensive_nested_getattr_user_read_is_counted(gate) -> None:
    """#1790 correction 5: the census must see through the defensive spelling.

    Routes that cannot assume ``request`` carries ``state`` at all read it as
    ``getattr(getattr(request, "state", None), "user", None)``. The original
    matcher required ``args[0]`` to be a ``.state`` attribute, so this form was
    invisible: capabilities.py carried a live dict-shaped read the ratchet
    certified as clean.
    """
    source = (
        "def handler(request):\n"
        "    user = getattr(getattr(request, 'state', None), 'user', None) or {}\n"
        "    probed = hasattr(getattr(request, 'state', None), 'user')\n"
    )
    [violation] = gate.scan_source(ROUTE, source)
    assert violation.key() == f"state_user_access::{ROUTE}"
    assert violation.detail.startswith("2 ")


def test_defensive_nested_getattr_non_user_attribute_is_not_a_violation(gate) -> None:
    """Only ``user`` is the dict-shaped principal; other state keys stay clean."""
    source = (
        "def handler(request):\n"
        "    rid = getattr(getattr(request, 'state', None), 'request_id', None)\n"
        "    org = getattr(getattr(request, 'state', None), 'org_id', None)\n"
    )
    assert gate.scan_source(ROUTE, source) == []


def test_principal_carrier_is_not_a_violation(gate) -> None:
    source = "def handler(request):\n    return request.state.principal.user_id\n"
    assert gate.scan_source(ROUTE, source) == []


def test_parallel_principal_class_is_a_violation_outside_the_owner(gate) -> None:
    source = "class SessionUser:\n    roles: list[str]\n"
    rel = "packages/maistro-canvas/src/maistro_canvas/x.py"
    [violation] = gate.scan_source(rel, source)
    assert violation.key() == f"parallel_principal_class::{rel}::SessionUser"
    assert gate.scan_source("packages/maistro-core/src/maistro/identity/principal.py", source) == []


def test_new_violation_needs_a_grant_landed_at_the_base(gate) -> None:
    current = {"a", "b"}
    assert gate.compare(current, current, {"a"}, set()) == [
        "b: NEW parallel principal surface absent from the trusted base and not previously authorized"
    ]
    assert gate.compare(current, current, {"a"}, {"b"}) == []


def test_candidate_ledger_must_match_the_tree(gate) -> None:
    failures = gate.compare({"a"}, {"a", "fixed"}, {"a", "fixed"}, set())
    assert failures == ["fixed: fixed -- delete it from the candidate ledger"]


def test_main_reaches_verdicts_through_the_bundled_identity(
    gate, monkeypatch, tmp_path, capsys
) -> None:
    """#319: main() resolves the implementation identity before judging.

    Drives the whole verdict path with a fake provenance namespace that, like
    the real one, carries bundled_implementation_fingerprint: the identity
    resolves first inside the trusted-state try block, the record prints, and
    both a clean pass and an unauthorized-debt fail reach their exit code.
    """
    baseline = tmp_path / "principal-identity-baseline.json"
    baseline.write_text(json.dumps({"tolerated": {}}), encoding="utf-8")
    monkeypatch.setattr(gate, "BASELINE", baseline)
    trusted = SimpleNamespace(base_sha="0" * 40, loads=lambda default=None: {"tolerated": {}})
    provenance = SimpleNamespace(
        RatchetProvenanceError=RuntimeError,
        resolve_baseline=lambda *_a, **_k: trusted,
        require_measurement=lambda *_a, **_k: None,
        require_metric_version=lambda *_a, **_k: None,
        load_authorizations=lambda *_a, **_k: {},
        head_sha=lambda *_a: "c" * 40,
        Provenance=lambda **_k: SimpleNamespace(render=lambda: "fixture provenance"),
        bundled_implementation_fingerprint=lambda *_a, **_k: "bundled-sha256:fake",
    )
    monkeypatch.setattr(gate, "_provenance", lambda: provenance)
    monkeypatch.setattr(sys, "argv", ["check-principal-identity.py"])

    monkeypatch.setattr(gate, "collect_violations", lambda: ([], 3))
    assert gate.main() == 0
    out = capsys.readouterr().out
    assert "fixture provenance" in out
    assert "ok: 0 tolerated principal-identity violation(s), none new" in out

    violation = gate.Violation(
        "state_user_access", "packages/hive-conductor/backend/routes/new.py", "", "1 access"
    )
    monkeypatch.setattr(gate, "collect_violations", lambda: ([violation], 3))
    assert gate.main() == 1
    assert "NEW parallel principal surface" in capsys.readouterr().err
