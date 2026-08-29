"""Tests for the merge-time actual-base AC-state guard (#620)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

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

    regressions = gate._actual_base_regressions(base, candidate)

    assert any("21.5 falls below the floor of 22.0" in line for line in regressions)


@pytest.mark.ac("SPEC-082926-25a2/AC-7")
def test_actual_base_guard_preserves_debt_improvement_too(gate) -> None:
    base = _totals(gate, debt=90)
    candidate = _totals(gate, debt=95)

    regressions = gate._actual_base_regressions(base, candidate)

    assert any("95 exceeds the ceiling of 90" in line for line in regressions)


@pytest.mark.ac("SPEC-082926-25a2/AC-7")
def test_actual_base_guard_allows_improvement_to_become_next_base(gate) -> None:
    base = _totals(gate, coverage=22.0, debt=90)
    candidate = _totals(gate, coverage=22.5, debt=85)

    assert gate._actual_base_regressions(base, candidate) == []


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
