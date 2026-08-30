from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-ac-state.py"
spec = importlib.util.spec_from_file_location("_ac_state_review_slack", SCRIPT)
assert spec and spec.loader
gate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gate
spec.loader.exec_module(gate)


def test_pull_request_improvement_is_informational(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")

    assert gate._review_slack_policy(["design_coverage: 31.7, floor still says 31.2"]) == []

    out = capsys.readouterr().out
    assert "no bank is required" in out
    assert "branch notes are not a synchronization requirement" in out


def test_merge_group_keeps_the_existing_slack_policy(monkeypatch):
    seen: list[list[str]] = []

    def original(improvements: list[str]) -> list[str]:
        seen.append(improvements)
        return ["still-blocked"]

    monkeypatch.setattr(gate, "_ORIGINAL_SLACK_POLICY", original)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "merge_group")

    assert gate._review_slack_policy(["x"]) == ["still-blocked"]
    assert seen == [["x"]]


def test_public_ratchet_installs_and_restores_review_policy(monkeypatch):
    def previous(_improvements: list[str]) -> list[str]:
        return ["previous"]

    def fake_ratchet(_totals, _measured, _bank):
        assert gate._impl._slack_this_run_enforces is gate._review_slack_policy
        return 0

    monkeypatch.setattr(gate._impl, "_slack_this_run_enforces", previous)
    monkeypatch.setattr(gate._impl, "ratchet", fake_ratchet)

    assert gate.ratchet({}, measured=True, bank=False) == 0
    assert gate._impl._slack_this_run_enforces is previous
