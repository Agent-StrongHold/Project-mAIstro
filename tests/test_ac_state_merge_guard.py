"""Tests for the merge-time actual-base AC-state guard (#620)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

#: This guard is about movement against the actual base, not about grants, so
#: every case here states that there are none. Spelled rather than defaulted:
#: the authorized floors are an argument the caller must decide about, and a
#: default of "no grants" is exactly the silent answer that would let the
#: merge-group comparison forget them again (#662).
NO_GRANTS: dict[str, float] = {}

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-ac-state.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("check_ac_state_public", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate():
    return _load_gate()


def _totals(gate, *, coverage: float = 20.0, debt: int = 100):
    totals = dict.fromkeys(gate.RATCHETED, 0)
    totals["specs_awaiting_retrofit"] = debt
    totals["design_coverage"] = coverage
    return totals


@pytest.mark.ac("SPEC-082926-25a2/AC-7")
def test_actual_base_floor_preserves_merge_group_only_improvement(gate) -> None:
    """A stale note at 20 must not permit losing an actual base floor of 22."""
    base = _totals(gate, coverage=22.0)
    candidate = _totals(gate, coverage=21.5)

    regressions = gate._actual_base_regressions(base, candidate, NO_GRANTS)

    assert any("21.5 falls below the floor of 22.0" in line for line in regressions)


@pytest.mark.ac("SPEC-082926-25a2/AC-7")
def test_actual_base_guard_preserves_debt_improvement_too(gate) -> None:
    base = _totals(gate, debt=90)
    candidate = _totals(gate, debt=95)

    regressions = gate._actual_base_regressions(base, candidate, NO_GRANTS)

    assert any("95 exceeds the ceiling of 90" in line for line in regressions)


@pytest.mark.ac("SPEC-082926-25a2/AC-7")
def test_actual_base_guard_allows_improvement_to_become_next_base(gate) -> None:
    base = _totals(gate, coverage=22.0, debt=90)
    candidate = _totals(gate, coverage=22.5, debt=85)

    assert gate._actual_base_regressions(base, candidate, NO_GRANTS) == []


@pytest.mark.ac("SPEC-082926-25a2/AC-7")
def test_merge_group_requires_actual_base_but_pull_request_does_not(gate, monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_EVENT_NAME", "merge_group")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/gh-readonly-queue/develop/pr-621")
    assert gate._needs_actual_base() is True

    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    assert gate._needs_actual_base() is False


@pytest.mark.ac("SPEC-082926-25a2/AC-7")
def test_protected_push_uses_actual_parent_but_feature_push_keeps_review_semantics(
    gate, monkeypatch
) -> None:
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/develop")
    assert gate._needs_actual_base() is True

    monkeypatch.setenv("GITHUB_REF", "refs/heads/feat/example")
    assert gate._needs_actual_base() is False


@pytest.mark.ac("SPEC-082926-25a2/AC-7")
def test_actual_base_revision_delegates_to_the_shared_resolver(
    gate, monkeypatch, tmp_path: Path
) -> None:
    """#664 replaced the guard's own event parsing with ci_base_revision's
    single fail-closed resolver. This pins that ``_actual_base_revision``
    still answers correctly through that delegation, not just that the
    shared resolver itself works (already covered by test_ci_base_revision.py)."""
    sha = "a" * 40
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"before": sha}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))

    assert gate._actual_base_revision() == sha


@pytest.mark.ac("SPEC-082926-25a2/AC-7")
def test_main_reports_the_shared_resolver_failure(
    gate, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A merge group with no resolvable base SHA fails closed before the
    ratchet ever runs, and says why."""
    monkeypatch.delenv(gate._BASE_MEASUREMENT, raising=False)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "merge_group")
    monkeypatch.delenv("MANDATE_BASE_SHA", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)

    assert gate.main([]) == 1
    err = capsys.readouterr().out
    assert "FAIL: this run requires an immutable AC-state base revision:" in err
