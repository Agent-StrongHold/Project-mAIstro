"""Tests for scripts/npm_audit_gate.py (the canvas frontend's npm audit gate).

The report fixtures mirror the real shape of ``npm audit --json`` captured on
2026-11-18 against packages/maistro-canvas/frontend (picomatch
GHSA-fc5q-39xc-vjpf cascading through fdir/tinyglobby/vite/vitest/
@vitejs/plugin-react): ``via`` mixes real advisory objects (with a GHSA URL)
with bare strings naming the package that carries the advisory.

That advisory stopped being reported by npm's advisory database the same day
(zero advisories against the identical lock, picomatch still 4.0.7), and the
gate's two-way ratchet retired the production waiver (#2375). So every test
here injects its waivers explicitly via ``_run(allowed=...)`` — none depends
on the production ALLOWED ledger except the one that pins the retirement.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

PatchedFix = {"name": "vitest", "version": "3.1.4", "isSemVerMajor": True}


def _picomatch_report(
    advisory_id: str = "GHSA-fc5q-39xc-vjpf", severity: str = "high"
) -> dict[str, Any]:
    """The real cascade shape: one root advisory object, five cascade strings."""
    return {
        "auditReportVersion": 2,
        "vulnerabilities": {
            "picomatch": {
                "name": "picomatch",
                "severity": severity,
                "isDirect": False,
                "via": [
                    {
                        "source": 1247710,
                        "name": "picomatch",
                        "dependency": "picomatch",
                        "title": "picomatch vulnerable to ReDoS through single-branch repeated extglobs",
                        "url": f"https://github.com/advisories/{advisory_id}",
                        "severity": severity,
                        "cwe": ["CWE-1333"],
                        "cvss": {
                            "score": 7.5,
                            "vectorString": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H",
                        },
                        "range": "<=4.0.7",
                    }
                ],
                "effects": ["fdir", "tinyglobby", "vite", "vitest"],
                "range": "*",
                "nodes": ["node_modules/picomatch"],
                "fixAvailable": PatchedFix,
            },
            "fdir": {
                "name": "fdir",
                "severity": severity,
                "via": ["picomatch"],
                "effects": ["tinyglobby"],
                "range": ">=5.2.1",
                "nodes": ["node_modules/fdir"],
                "fixAvailable": PatchedFix,
            },
            "tinyglobby": {
                "name": "tinyglobby",
                "severity": severity,
                "via": ["fdir", "picomatch"],
                "effects": ["vitest", "vite"],
                "range": "*",
                "nodes": ["node_modules/tinyglobby"],
                "fixAvailable": PatchedFix,
            },
            "vite": {
                "name": "vite",
                "severity": severity,
                "via": ["picomatch", "tinyglobby"],
                "effects": ["@vitejs/plugin-react"],
                "range": ">=6.3.0-beta.0",
                "nodes": ["node_modules/vite"],
                "fixAvailable": {
                    "name": "@vitejs/plugin-react",
                    "version": "5.2.0",
                    "isSemVerMajor": True,
                },
            },
            "@vitejs/plugin-react": {
                "name": "@vitejs/plugin-react",
                "severity": severity,
                "via": ["vite"],
                "effects": [],
                "range": ">=6.0.0-beta.0",
                "nodes": ["node_modules/@vitejs/plugin-react"],
                "fixAvailable": True,
            },
            "vitest": {
                "name": "vitest",
                "severity": severity,
                "via": ["picomatch", "tinyglobby", "vite"],
                "effects": [],
                "range": ">=3.1.2",
                "nodes": ["node_modules/vitest"],
                "fixAvailable": PatchedFix,
            },
        },
        "metadata": {"vulnerabilities": {"high": 6, "critical": 0, "total": 6}},
    }


@pytest.fixture()
def gate():
    path = Path(__file__).resolve().parents[1] / "scripts" / "npm_audit_gate.py"
    spec = importlib.util.spec_from_file_location("npm_audit_gate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_report(tmp_path: Path, report: dict[str, Any]) -> str:
    path = tmp_path / "npm-audit.json"
    path.write_text(json.dumps(report))
    return str(path)


def _run(
    gate, tmp_path: Path, report: dict[str, Any], allowed: dict[str, str] | None = None
) -> tuple[int, str]:
    if allowed is not None:
        gate.ALLOWED.clear()
        gate.ALLOWED.update(allowed)
    rc = gate.audit_report(_write_report(tmp_path, report))
    return rc


def test_a_triaged_waiver_passes_the_real_cascade(gate, tmp_path, capsys) -> None:
    """A triaged waiver covers the advisory AND every package it cascades into."""
    rc = _run(
        gate,
        tmp_path,
        _picomatch_report(),
        allowed={"GHSA-fc5q-39xc-vjpf": "triaged 2026-10-19: no patched picomatch release"},
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "allowed: GHSA-fc5q-39xc-vjpf" in out
    # every cascaded package is attributed to the one root advisory
    assert "fdir" in out and "tinyglobby" in out and "vitest" in out
    assert "npm audit OK" in out


def test_an_unwaived_advisory_fails_naming_the_id_and_affecting_packages(
    gate, tmp_path, capsys
) -> None:
    rc = _run(gate, tmp_path, _picomatch_report(), allowed={})
    out = capsys.readouterr().out
    assert rc == 1
    assert "GHSA-fc5q-39xc-vjpf" in out
    # npm's fixAvailable is quoted verbatim as the hint (its forced fix is a
    # lie here — vitest 3.1.4 still depends on vulnerable picomatch — so the
    # gate surfaces it rather than asserting unavailability it cannot know).
    assert "fix available: vitest@3.1.4 (breaking)" in out
    assert "@vitejs/plugin-react" in out  # the deepest cascade is named as affected


def test_a_new_advisory_on_the_same_chain_is_not_covered_by_the_waiver(
    gate, tmp_path, capsys
) -> None:
    """Two advisories in one report: the waived one passes, the other blocks."""
    report = _picomatch_report()
    report["vulnerabilities"]["picomatch"]["via"].append(
        {
            "source": 9999999,
            "name": "picomatch",
            "dependency": "picomatch",
            "title": "picomatch vulnerable to something new",
            "url": "https://github.com/advisories/GHSA-new-new-new",
            "severity": "high",
            "range": "<=4.0.7",
        }
    )
    rc = _run(
        gate,
        tmp_path,
        report,
        allowed={"GHSA-fc5q-39xc-vjpf": "triaged 2026-10-19: no patched picomatch release"},
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "GHSA-new-new-new" in out
    assert "outside the triaged allowlist" in out
    # the verdict fails fast on the blocker: the gate names the new ID and
    # never reaches the allowed-entries printout (waivers are acknowledged
    # only once nothing blocks)


def test_the_cascade_direction_is_two_sided(gate, tmp_path, capsys) -> None:
    """With the waiver removed, every cascade member fails — not just picomatch."""
    rc = _run(gate, tmp_path, _picomatch_report(advisory_id="GHSA-some-untriaged"), allowed={})
    out = capsys.readouterr().out
    assert rc == 1
    for package in ("picomatch", "fdir", "tinyglobby", "vite", "vitest", "@vitejs/plugin-react"):
        assert package in out


def test_moderate_and_low_advisories_never_block(gate, tmp_path) -> None:
    rc = _run(gate, tmp_path, _picomatch_report(severity="moderate"), allowed={})
    assert rc == 0


def test_a_critical_advisory_blocks_like_a_high_one(gate, tmp_path) -> None:
    rc = _run(
        gate, tmp_path, _picomatch_report(advisory_id="GHSA-crit", severity="critical"), allowed={}
    )
    assert rc == 1


def test_an_empty_report_is_an_infrastructure_failure_not_a_verdict(gate, tmp_path, capsys) -> None:
    path = tmp_path / "npm-audit.json"
    path.write_text("")
    rc = gate.audit_report(str(path))
    out = capsys.readouterr().out
    assert rc == 3
    assert "infrastructure failure" in out


def test_an_unparseable_report_is_an_infrastructure_failure(gate, tmp_path, capsys) -> None:
    path = tmp_path / "npm-audit.json"
    path.write_text("<html>registry 502 page</html>")
    rc = gate.audit_report(str(path))
    out = capsys.readouterr().out
    assert rc == 3
    assert "infrastructure failure" in out


def test_an_npm_registry_error_payload_is_an_infrastructure_failure(gate, tmp_path, capsys) -> None:
    """ENOTFOUND-style payloads mean the audit never ran — never a clean verdict."""
    path = tmp_path / "npm-audit.json"
    path.write_text(json.dumps({"error": {"code": "ENOTFOUND", "summary": "registry unreachable"}}))
    rc = gate.audit_report(str(path))
    out = capsys.readouterr().out
    assert rc == 3
    assert "registry unreachable" in out


def test_a_malformed_vulnerabilities_object_is_an_infrastructure_failure(gate, tmp_path) -> None:
    rc = _run(gate, tmp_path, {"vulnerabilities": ["picomatch"]})
    assert rc == 3


def test_a_waiver_whose_advisory_stopped_being_reported_is_stale(gate, tmp_path, capsys) -> None:
    """A waiver for an advisory the report no longer lists must fail until deleted."""
    report = {
        "auditReportVersion": 2,
        "vulnerabilities": {
            "lodash": {
                "name": "lodash",
                "severity": "low",
                "via": [
                    {
                        "source": 42,
                        "name": "lodash",
                        "title": "prototype pollution",
                        "url": "https://github.com/advisories/GHSA-low",
                        "severity": "low",
                        "range": "<4.17.21",
                    }
                ],
                "effects": [],
                "range": "<4.17.21",
                "nodes": ["node_modules/lodash"],
                "fixAvailable": True,
            }
        },
        "metadata": {"vulnerabilities": {"low": 1, "total": 1}},
    }
    rc = _run(gate, tmp_path, report, allowed={"GHSA-gone": "waived last quarter"})
    out = capsys.readouterr().out
    assert rc == 1
    assert "stale" in out
    assert "GHSA-gone" in out
    assert "delete it from ALLOWED" in out


def test_a_fully_clean_report_passes(gate, tmp_path, capsys) -> None:
    """The post-retirement shape: zero advisories, empty allowlist, exit 0.

    This is the live production situation since npm's advisory database
    stopped reporting GHSA-fc5q-39xc-vjpf on 2026-11-18 (#2375).
    """
    report = {
        "auditReportVersion": 2,
        "vulnerabilities": {},
        "metadata": {
            "vulnerabilities": {
                "info": 0,
                "low": 0,
                "moderate": 0,
                "high": 0,
                "critical": 0,
                "total": 0,
            }
        },
    }
    rc = _run(gate, tmp_path, report, allowed={})
    out = capsys.readouterr().out
    assert rc == 0
    assert "npm audit OK (0 advisories reported, all triaged in ALLOWED)" in out


def test_the_retired_picomatch_waiver_is_gone_from_the_production_allowlist(gate) -> None:
    """The production ledger carries no waiver npm no longer justifies (#2375).

    Regression pin for the 2026-11-18 CI red: npm stopped reporting
    GHSA-fc5q-39xc-vjpf while the lock still carried picomatch 4.0.7, so the
    stale waiver failed every run until it was deleted. Re-adding it without
    an actively reported advisory re-breaks the same way — triage belongs in
    ALLOWED only while the advisory is real.
    """
    assert "GHSA-fc5q-39xc-vjpf" not in gate.ALLOWED


def test_usage_error(gate) -> None:
    assert gate.main(["npm_audit_gate.py"]) == 2
    assert gate.main(["npm_audit_gate.py", "a", "b"]) == 2
