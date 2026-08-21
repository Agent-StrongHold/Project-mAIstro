"""Tests for the noise-aware hill-climber accept criterion."""

from __future__ import annotations

from services.hill_climber import HillClimber


def _hc() -> HillClimber:
    return HillClimber(
        dag_id="d1", all_evals=["a", "b", "c", "d"], target_count=2, held_out_count=2
    )


def test_within_noise_improvement_rejected() -> None:
    """A +3 gain (below the 5-point noise floor) must NOT be accepted — it's noise."""
    hc = _hc()
    res = hc.evaluate_mutation(
        target_evals=["a", "b"],
        held_out_evals=["c", "d"],
        baseline_scores={"a": 50, "b": 50, "c": 50, "d": 50},
        mutated_scores={"a": 53, "b": 50, "c": 50, "d": 50},  # +3 on a, within noise
    )
    assert res.mutation_accepted is False
    assert "no improvement" in res.reason


def test_above_noise_improvement_accepted() -> None:
    """A +6 gain (above the 5-point noise floor) is a real improvement → accepted."""
    hc = _hc()
    res = hc.evaluate_mutation(
        target_evals=["a", "b"],
        held_out_evals=["c", "d"],
        baseline_scores={"a": 50, "b": 50, "c": 50, "d": 50},
        mutated_scores={"a": 56, "b": 50, "c": 50, "d": 50},  # +6 on a, clears noise
    )
    assert res.mutation_accepted is True


def test_held_out_regression_rejects() -> None:
    """A real target gain is rejected if a held-out eval regresses beyond 2x the floor."""
    hc = _hc()
    res = hc.evaluate_mutation(
        target_evals=["a", "b"],
        held_out_evals=["c", "d"],
        baseline_scores={"a": 50, "b": 50, "c": 50, "d": 50},
        mutated_scores={"a": 60, "b": 50, "c": 50, "d": 38},  # +10 on a, -12 on held-out d
    )
    assert res.mutation_accepted is False
    assert "held-out" in res.reason


def test_stdev_raises_the_bar() -> None:
    """With a high per-eval stdev, a +6 gain no longer clears ~2 sigma → rejected."""
    hc = _hc()
    res = hc.evaluate_mutation(
        target_evals=["a", "b"],
        held_out_evals=["c", "d"],
        baseline_scores={"a": 50, "b": 50, "c": 50, "d": 50},
        mutated_scores={"a": 56, "b": 50, "c": 50, "d": 50},  # +6
        score_stdev={"a": 8.0},  # 2*sigma = 16 > 6 → not significant
    )
    assert res.mutation_accepted is False
