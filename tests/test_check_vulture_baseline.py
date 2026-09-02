"""Tests for the vulture per-identity debt ledger.

The script is a CI gate, so the properties that matter are that it *fails* — by
name — on a finding the ledger has not reviewed, and on a recorded identity that
no longer occurs (a stale entry would silently absorb a later regression). A
gate that silently passes is worse than no gate.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-vulture-baseline.py"
BASELINE = ROOT / "quality" / "vulture-baseline.json"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_vulture_baseline", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RULES = [
    {
        "id": "route-surface",
        "path_regex": r"routes\.py$",
        "message_regex": "unused function",
        "findings": ["pkg/routes.py::unused function 'get_thing'"],
    },
    {
        "id": "model-fields",
        "message_regex": "unused attribute",
        "findings": ["pkg/models.py::unused attribute 'field_a'"],
    },
]


def _finding(gate, path, message, line=10, confidence=60):
    return gate.Finding(path=path, line=line, message=message, confidence=confidence)


def _payload(rules):
    return {"version": 1, "owner": "@test", "policy": "test", "rules": rules}


def _baseline_with(tmp_path, rules):
    path = tmp_path / "vulture-baseline.json"
    path.write_text(json.dumps(_payload(rules)), encoding="utf-8")
    return path


def _trusted(gate, rules):
    """Stand in for the merge-base ledger without consulting repository history."""
    prov = gate._provenance()
    return prov.Baseline(
        text=json.dumps(_payload(rules)),
        origin="base",
        base_sha="0" * 40,
        path=Path("quality/vulture-baseline.json"),
    )


def _run_main(gate, monkeypatch, tmp_path, rules, findings, argv=None):
    candidate = _payload(rules)
    monkeypatch.setattr(gate, "BASELINE", _baseline_with(tmp_path, rules))
    monkeypatch.setattr(gate, "_load_baseline", lambda *args, **kwargs: candidate)
    monkeypatch.setattr(gate, "_run_vulture", lambda args: findings)

    args = argv if argv is not None else ["pkg"]
    if "--update" not in args:
        trusted_ref = _trusted(gate, rules)
        monkeypatch.setattr(
            gate,
            "_trusted_state",
            lambda measured, prov: (trusted_ref, rules, {}),
        )
    return gate.main(args)


def test_committed_baseline_has_explicit_identities():
    """The real ledger is per-identity: every rule carries a sorted findings
    list, and the fungible count/digest fields are gone."""
    rules = json.loads(BASELINE.read_text(encoding="utf-8"))["rules"]
    assert rules
    for rule in rules:
        assert isinstance(rule.get("findings"), list), f"{rule['id']} has no findings ledger"
        assert rule["findings"] == sorted(rule["findings"])
        assert "finding_count" not in rule and "finding_sha256" not in rule


def test_stable_key_ignores_line_movement(gate):
    a = _finding(gate, "pkg/x.py", "unused function 'f'", line=10)
    b = _finding(gate, "pkg/x.py", "unused function 'f'", line=99)
    assert a.stable_key == b.stable_key


def test_matching_ledger_passes(gate, monkeypatch, tmp_path):
    findings = [
        _finding(gate, "pkg/routes.py", "unused function 'get_thing'"),
        _finding(gate, "pkg/models.py", "unused attribute 'field_a'"),
    ]
    assert _run_main(gate, monkeypatch, tmp_path, RULES, findings) == 0


def test_new_identity_fails_by_name(gate, monkeypatch, tmp_path, capsys):
    findings = [
        _finding(gate, "pkg/routes.py", "unused function 'get_thing'"),
        _finding(gate, "pkg/routes.py", "unused function 'brand_new'"),
        _finding(gate, "pkg/models.py", "unused attribute 'field_a'"),
    ]
    assert _run_main(gate, monkeypatch, tmp_path, RULES, findings) == 1
    assert "brand_new" in capsys.readouterr().err


def test_stale_identity_fails_until_pruned(gate, monkeypatch, tmp_path, capsys):
    findings = [_finding(gate, "pkg/models.py", "unused attribute 'field_a'")]
    assert _run_main(gate, monkeypatch, tmp_path, RULES, findings) == 1
    err = capsys.readouterr().err
    assert "get_thing" in err
    assert "prune" in err


def test_duplicate_identities_compare_as_multiset(gate, monkeypatch, tmp_path):
    """Two same-named findings in one file are two ledger entries; losing one
    of them must fail, not vanish behind set semantics."""
    rules = [
        {
            "id": "dupes",
            "message_regex": "unused function",
            "findings": ["pkg/x.py::unused function 'f'", "pkg/x.py::unused function 'f'"],
        }
    ]
    both = [
        _finding(gate, "pkg/x.py", "unused function 'f'", line=1),
        _finding(gate, "pkg/x.py", "unused function 'f'", line=50),
    ]
    assert _run_main(gate, monkeypatch, tmp_path, rules, both) == 0
    assert _run_main(gate, monkeypatch, tmp_path, rules, both[:1]) == 1


def test_unreachable_code_is_never_allowlisted(gate, monkeypatch, tmp_path, capsys):
    findings = [
        _finding(gate, "pkg/routes.py", "unused function 'get_thing'"),
        _finding(gate, "pkg/models.py", "unused attribute 'field_a'"),
        _finding(gate, "pkg/routes.py", "unreachable code after 'return'", confidence=100),
    ]
    assert _run_main(gate, monkeypatch, tmp_path, RULES, findings) == 1
    assert "must be fixed" in capsys.readouterr().err


def test_update_banks_current_identities(gate, monkeypatch, tmp_path):
    rules = [dict(RULES[0], findings=[]), dict(RULES[1])]
    findings = [
        _finding(gate, "pkg/routes.py", "unused function 'get_thing'"),
        _finding(gate, "pkg/models.py", "unused attribute 'field_a'"),
    ]
    assert _run_main(gate, monkeypatch, tmp_path, rules, findings, argv=["--update", "pkg"]) == 0
    written = json.loads(gate.BASELINE.read_text(encoding="utf-8"))["rules"]
    assert written[0]["findings"] == ["pkg/routes.py::unused function 'get_thing'"]
    assert _run_main(gate, monkeypatch, tmp_path, written, findings) == 0


def test_update_drops_legacy_count_and_digest(gate, monkeypatch, tmp_path):
    rules = [dict(RULES[0], finding_count=1, finding_sha256="0" * 64)]
    findings = [_finding(gate, "pkg/routes.py", "unused function 'get_thing'")]
    assert _run_main(gate, monkeypatch, tmp_path, rules, findings, argv=["--update", "pkg"]) == 0
    written = json.loads(gate.BASELINE.read_text(encoding="utf-8"))["rules"][0]
    assert "finding_count" not in written and "finding_sha256" not in written


def test_update_refuses_unbankable_findings(gate, monkeypatch, tmp_path, capsys):
    findings = [_finding(gate, "pkg/routes.py", "unreachable code after 'return'")]
    baseline_path = _baseline_with(tmp_path, [dict(RULES[0])])
    before = baseline_path.read_text(encoding="utf-8")
    monkeypatch.setattr(gate, "BASELINE", baseline_path)
    monkeypatch.setattr(gate, "_load_baseline", lambda *args, **kwargs: _payload([dict(RULES[0])]))
    monkeypatch.setattr(gate, "_run_vulture", lambda args: findings)
    assert gate.main(["--update", "pkg"]) == 1
    assert "refused" in capsys.readouterr().err
    assert baseline_path.read_text(encoding="utf-8") == before
