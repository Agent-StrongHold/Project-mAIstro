"""Tests for the reachability ratchet.

The script is a CI gate, so the property that matters is that it *fails* on a
newly-unreachable module. A gate that silently passes is worse than no gate —
it reads as evidence the defect class is handled.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-reachability.py"
BASELINE = ROOT / "quality" / "reachability-baseline.json"


@pytest.fixture(scope="module")
def check():
    spec = importlib.util.spec_from_file_location("check_reachability", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_baseline_matches_the_tree(check):
    """The committed baseline is the current truth — otherwise the first CI run
    after any merge fails for reasons unrelated to that merge."""
    unreachable, _ = check.unreachable_modules()
    baseline = sorted(json.loads(BASELINE.read_text())["unreachable"])
    stale = sorted(set(baseline) - set(unreachable))
    added = sorted(set(unreachable) - set(baseline))
    if stale:
        print(f"::error title=Reachability baseline stale::{','.join(stale)}")
    if added:
        print(f"::error title=New unreachable modules::{','.join(added)}")
    assert baseline == unreachable


def test_entry_points_are_reachable(check):
    """A graph that roots at nothing reports everything as dead and looks like a
    catastrophic finding. Assert the roots resolved."""
    unreachable, total = check.unreachable_modules()
    assert total > 500
    assert "main" not in unreachable
    assert "maistro.container" not in unreachable
    assert "maistro.conduit" not in unreachable


def test_known_wired_subsystems_are_reachable(check):
    """Regression guard for the wiring this ratchet was built alongside: if any
    of these fall off a call path again, that is the #344/ADR-064 bug returning."""
    unreachable, _ = check.unreachable_modules()
    for mod in (
        "maistro.security.redact",
        "maistro.security.log_redaction",
        "maistro.memory.episodic.decay_driver",
        "maistro.skills.parser",
    ):
        assert mod not in unreachable, f"{mod} lost its production call path"


def test_new_unreachable_module_fails_the_gate(check, tmp_path, monkeypatch, capsys):
    """The gate's whole job. Simulated by shrinking the baseline rather than
    writing a file into packages/, so a crashed test cannot leave a stray module
    behind in the tree."""
    unreachable, _ = check.unreachable_modules()
    assert unreachable, "expected a non-empty baseline to borrow an entry from"

    shrunk = tmp_path / "baseline.json"
    shrunk.write_text(json.dumps({"unreachable": unreachable[1:]}))
    monkeypatch.setattr(check, "BASELINE", shrunk)

    assert check.main() == 1
    assert unreachable[0] in capsys.readouterr().out


def test_module_becoming_reachable_fails_until_the_baseline_is_pruned(
    check, tmp_path, monkeypatch, capsys
):
    """Wiring a module up is good news, and it still has to be banked.

    The baseline is a record of what is *currently* unreachable, so an entry
    that is no longer true is retained slack: it would silently absorb a later
    module going unreachable, and the gate would say nothing. Failing here
    costs one line — delete the stale entry — and the message says which.
    """
    unreachable, _ = check.unreachable_modules()
    grown = tmp_path / "baseline.json"
    grown.write_text(json.dumps({"unreachable": [*unreachable, "maistro.nonexistent_module"]}))
    monkeypatch.setattr(check, "BASELINE", grown)

    assert check.main() == 1
    out = capsys.readouterr().out
    assert "maistro.nonexistent_module" in out
    assert "must shrink" in out
