"""Tests for the frontend typed-client ratchet (Workspace cutover P0.3, #1048)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-frontend-typed-client.py"
LOGIN = ROOT / "packages/hive-conductor/frontend/src/pages/Login.tsx"
API = ROOT / "packages/hive-conductor/frontend/src/lib/api.ts"
AGENTS = ROOT / "packages/hive-conductor/frontend/src/pages/Agents.tsx"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_frontend_typed_client", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_raw_fetch_outside_lib_is_measured(gate) -> None:
    violations = gate._scan_raw_fetch(LOGIN)
    assert any(item.kind == "raw_fetch" and item.line_no == 83 for item in violations)


def test_raw_fetch_inside_lib_is_ignored(gate) -> None:
    assert gate._scan_raw_fetch(API) == []


def test_hand_typed_in_pages_is_measured(gate) -> None:
    violations = gate._scan_hand_typed(AGENTS)
    assert any(item.kind == "hand_typed" and item.subject == "Agent" for item in violations)


def test_waiver_skips_a_call_site(gate, tmp_path: Path) -> None:
    page = tmp_path / "Waived.tsx"
    page.write_text(
        'fetch("/v1/sidecar"); // frontend-typed-client: allow served by sidecar\n',
        encoding="utf-8",
    )
    lines = page.read_text(encoding="utf-8").splitlines()
    assert gate._is_waived(lines, 0)


def test_new_debt_needs_authorization(gate) -> None:
    key = "raw_fetch::packages/hive-conductor/frontend/src/pages/Dashboard.tsx:51"
    failures = gate.compare({key}, set(), set(), set())
    assert any("NEW frontend typed-client debt" in failure for failure in failures)


def test_fixed_debt_must_leave_the_candidate_ledger(gate) -> None:
    key = "hand_typed::packages/hive-conductor/frontend/src/pages/Agents.tsx:20:Agent"
    assert gate.compare(set(), {key}, {key}, set()) == [
        f"{key}: fixed -- delete it from the candidate ledger"
    ]


def test_ci_typed_client_ratchet_has_full_candidate_history() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["lint-and-type-check"]["steps"]
    ratchets = [
        index
        for index, step in enumerate(steps)
        if "scripts/check-frontend-typed-client.py" in step.get("run", "")
    ]
    assert len(ratchets) == 1, "the lint job must run the typed-client ratchet"
    checkouts = [
        step
        for step in steps[: ratchets[0]]
        if step.get("uses", "").startswith("actions/checkout@")
    ]
    assert len(checkouts) == 1, "the ratchet needs one candidate checkout before it runs"
    checkout = checkouts[0]
    assert "if" not in checkout, "the trusted history must be available on every event"
    options = checkout.get("with", {})
    assert options.get("fetch-depth") == 0, "the ratchet needs its trusted base and ancestry"
    assert not {"ref", "path", "filter", "sparse-checkout"} & options.keys(), (
        "check the complete event candidate in the workspace, with its history"
    )


def test_main_reaches_verdicts_through_the_bundled_identity(
    gate, monkeypatch, tmp_path, capsys
) -> None:
    """#319: main() resolves the implementation identity before judging.

    The frontend guards (sources present, generated types present) are
    satisfied against a synthetic tree, the scan is substituted, and the fake
    provenance namespace carries bundled_implementation_fingerprint like the
    real one — so the identity resolves inside the trusted-state try block
    and both a clean pass and an unauthorized-debt fail reach their verdict.
    """
    frontend = tmp_path / "src"
    frontend.mkdir()
    types_gen = tmp_path / "types.gen.ts"
    types_gen.write_text("export type Nothing = never;\n", encoding="utf-8")
    monkeypatch.setattr(gate, "FRONTEND", frontend)
    monkeypatch.setattr(gate, "TYPES_GEN", types_gen)
    baseline = tmp_path / "frontend-typed-client-baseline.json"
    baseline.write_text(json.dumps({"tolerated": {}}), encoding="utf-8")
    monkeypatch.setattr(gate, "BASELINE", baseline)
    trusted = SimpleNamespace(
        base_sha="0" * 40,
        absent_at_base=False,
        loads=lambda default=None: {"tolerated": {}},
    )
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
    monkeypatch.setattr(sys, "argv", ["check-frontend-typed-client.py"])

    monkeypatch.setattr(gate, "collect_violations", lambda: ([], 4))
    assert gate.main() == 0
    out = capsys.readouterr().out
    assert "fixture provenance" in out
    assert "ok: 0 raw fetch and 0 hand-typed declaration(s) tolerated, none new" in out

    violation = gate.Violation("raw_fetch", "src/pages/Dashboard.tsx", 51, "", "raw call")
    monkeypatch.setattr(gate, "collect_violations", lambda: ([violation], 4))
    assert gate.main() == 1
    assert "NEW frontend typed-client debt" in capsys.readouterr().err
