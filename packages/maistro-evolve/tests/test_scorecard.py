"""Tests for the transparent multi-signal scorecard: gate vetoes, weighted
composite, per-kind provenance, and signal builders."""

from __future__ import annotations

from dataclasses import dataclass

from maistro_evolve.scorecard import (
    GateResult,
    MeasureKind,
    Scorecard,
    SignalScore,
    architecture_fit_signal,
    capability_signal,
    code_quality_signal,
)


def test_gate_failure_vetoes_composite() -> None:
    sc = Scorecard(
        gates=[GateResult("tests", False, "1 failed")],
        scores=[SignalScore("capability", MeasureKind.DERIVED, 0.9, 0.4, "high")],
    )
    assert sc.composite == 0.0
    assert sc.accepted is False


def test_composite_is_weighted_mean_when_gates_pass() -> None:
    sc = Scorecard(
        gates=[GateResult("tests", True, "ok")],
        scores=[
            SignalScore("a", MeasureKind.DERIVED, 1.0, 0.4, ""),
            SignalScore("b", MeasureKind.JUDGE, 0.5, 0.2, ""),
        ],
    )
    # (1.0*0.4 + 0.5*0.2) / (0.4+0.2) = 0.5 / 0.6
    assert sc.composite == round(0.5 / 0.6, 4)
    assert sc.accepted is True


def test_architecture_fit_signal_scores_by_side() -> None:
    @dataclass
    class V:
        winner: str
        cited: list[str]
        rationale: str

    v = V(winner="A", cited=["ADR-093"], rationale="isolation")
    assert architecture_fit_signal(v, 0.2, candidate_side="A").score == 1.0
    assert architecture_fit_signal(v, 0.2, candidate_side="B").score == 0.0
    tie = architecture_fit_signal(V("tie", [], ""), 0.2, candidate_side="A")
    assert tie.score == 0.5
    assert tie.kind is MeasureKind.JUDGE


def test_capability_signal_reports_delta() -> None:
    s = capability_signal(0.56, 0.70, 0.4)
    assert abs(s.score - 0.70) < 1e-9
    assert s.kind is MeasureKind.DERIVED
    assert "0.140" in s.rationale


def test_code_quality_signal_is_derived_with_math() -> None:
    @dataclass
    class CQ:
        composite: float = 0.38
        ruff: float | None = 0.11
        bandit: float | None = 0.125
        mypy: float | None = 1.0
        radon_cc: float | None = 0.9
        radon_mi: float | None = 0.66
        ruff_violations: int = 8
        bandit_issues: int = 4
        mypy_errors: int = 0
        avg_complexity: float = 7.0
        maintainability: float = 66.0
        tools_missing: list[str] = None  # type: ignore[assignment]

    s = code_quality_signal(CQ(tools_missing=[]), 0.25)
    assert s.kind is MeasureKind.DERIVED
    assert s.score == 0.38
    assert "ruff=0.11" in s.rationale and "bandit=0.12" in s.rationale


def test_explain_shows_verdict_and_kinds() -> None:
    sc = Scorecard(
        gates=[GateResult("tests", True, "ok"), GateResult("bandit_high", True, "none")],
        scores=[
            SignalScore("capability", MeasureKind.DERIVED, 0.7, 0.4, "swebench +0.14"),
            SignalScore("architecture_fit", MeasureKind.JUDGE, 1.0, 0.2, "winner=A [ADR-093]"),
        ],
    )
    out = sc.explain()
    assert "ACCEPTED" in out
    assert "[derived]" in out and "[judge]" in out
    assert "rationale:" in out
