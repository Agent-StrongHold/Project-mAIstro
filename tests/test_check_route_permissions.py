"""Tests for the authenticated route-permission ratchet (Workspace cutover P0.2).

The repo-level run lives in quality.yml beside check_enumerations.py, because
both import the hive app; these tests pin the registry contract without it.
"""

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
TODAY = date(2026, 10, 1)
_BASE = {"owner": "@someone", "disposition": "permanent", "reason": "because"}


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_route_permissions", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_prefix_is_the_first_v1_segment(gate) -> None:
    assert gate._v1_prefix("/v1/dags/{id}/run") == "/v1/dags"
    assert gate._v1_prefix("/health") is None


def test_entry_must_choose_permission_or_exemption(gate) -> None:
    assert gate.entry_problems("/v1/x", dict(_BASE), TODAY)
    both = {**_BASE, "permission": "x.write", "exempt_reason": "why"}
    assert gate.entry_problems("/v1/x", both, TODAY)
    assert not gate.entry_problems("/v1/x", {**_BASE, "permission": "x.write"}, TODAY)
    assert not gate.entry_problems("/v1/x", {**_BASE, "exempt_reason": "why"}, TODAY)


def test_temporary_exemption_needs_an_unexpired_date(gate) -> None:
    entry = {**_BASE, "exempt_reason": "why", "disposition": "temporary", "issue": 53}
    assert gate.entry_problems("/v1/x", entry, TODAY)
    assert gate.entry_problems("/v1/x", {**entry, "expires": "2026-09-30"}, TODAY)
    assert not gate.entry_problems("/v1/x", {**entry, "expires": "2026-12-31"}, TODAY)


def test_stale_or_public_registry_entries_fail_hard(gate) -> None:
    registry = {"/v1/gone": {**_BASE, "permission": "x"}, "/v1/open": {**_BASE, "permission": "x"}}
    problems = gate.registry_problems({"/v1/open"}, registry, {"/v1/open"}, TODAY)
    assert len(problems) == 2


def test_new_exemption_needs_a_grant_landed_at_the_base(gate) -> None:
    candidate = {"/v1/x": {**_BASE, "exempt_reason": "why"}}
    exemptions = gate.new_exemptions(candidate, {})
    assert exemptions == {"exempt::/v1/x"}
    assert gate.compare(set(), set(), set(), exemptions, set()) == [
        "exempt::/v1/x: NEW exemption needs an already-landed authorization"
    ]
    assert gate.new_exemptions(candidate, candidate) == set()


def test_declaring_a_prefix_requires_deleting_its_gap(gate) -> None:
    assert gate.compare(set(), {"/v1/x"}, {"/v1/x"}, set(), set()) == [
        "/v1/x: declared now -- delete it from the candidate ledger"
    ]


def test_main_reaches_verdicts_through_the_bundled_identity(
    gate, monkeypatch, tmp_path, capsys
) -> None:
    """#319: main() resolves the implementation identity before judging.

    The mounted-prefix census (which imports the live hive app in production)
    is substituted, the registries are pointed at synthetic files, and the
    fake provenance namespace carries bundled_implementation_fingerprint
    like the real one — so the identity resolves inside the trusted-state
    try block and both a clean pass and an undeclared-prefix fail reach their
    verdict.
    """
    registry = tmp_path / "route-permissions.json"
    registry.write_text(
        json.dumps({"prefixes": {"/v1/dags": {**_BASE, "permission": "dags.read"}}}),
        encoding="utf-8",
    )
    public = tmp_path / "public-routes.json"
    public.write_text(json.dumps({"routes": {}}), encoding="utf-8")
    baseline = tmp_path / "route-permissions-baseline.json"
    baseline.write_text(json.dumps({"tolerated": {}}), encoding="utf-8")
    monkeypatch.setattr(gate, "REGISTRY", registry)
    monkeypatch.setattr(gate, "PUBLIC_REGISTRY", public)
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
    monkeypatch.setattr(sys, "argv", ["check-route-permissions.py"])

    monkeypatch.setattr(gate, "mounted_prefixes", lambda: {"/v1/dags"})
    assert gate.main() == 0
    out = capsys.readouterr().out
    assert "fixture provenance" in out
    assert "ok: 1 declared, 0 tolerated undeclared prefix(es), none new" in out

    monkeypatch.setattr(gate, "mounted_prefixes", lambda: {"/v1/dags", "/v1/other"})
    assert gate.main() == 1
    assert "/v1/other: NEW undeclared route prefix" in capsys.readouterr().err
