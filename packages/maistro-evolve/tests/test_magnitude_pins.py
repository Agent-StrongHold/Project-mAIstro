"""#350 — magnitude pins for the fitness-score family (maistro-evolve).

``FitnessWeights`` is the reward policy of the RSI loop: which improvement
moves the loop chases. Its tests to date exercised weights through renormalised
composites or copied the dataclass, so a mutated table survived. The full table
plus the ADR's ladder invariants are now pinned against an INDEPENDENTLY
GOVERNED fixture (``governed_magnitudes_evolve.json`` in this directory) whose
numbers are stated apart from the implementation, and the composite formula is
calibrated with literal expected values so a mutated weight cannot pass by
dragging its own expectation along.

No production values are changed by this file; it only pins them.
"""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

import pytest

from maistro_evolve.scorecard import (
    FitnessWeights,
    MeasureKind,
    Scorecard,
    SignalScore,
)

_FIXTURE = json.loads(
    (Path(__file__).parent / "governed_magnitudes_evolve.json").read_text(encoding="utf-8")
)
_FX = _FIXTURE["entries"]
_TABLE = _FX["scorecard.FitnessWeights"]["value"]
_INVARIANTS = _FX["scorecard.FitnessWeights.ladder_invariants"]["value"]


def test_every_fitness_weight_is_pinned_by_the_governed_fixture() -> None:
    # The whole table, field by field — a dataclass field added or renamed
    # without a fixture decision fails here too (KeyError/AttributeError).
    w = FitnessWeights()
    assert {f.name: getattr(w, f.name) for f in fields(w)} == _TABLE


def test_spec_completion_is_the_largest_weight_in_the_system() -> None:
    w = FitnessWeights()
    assert w.spec_completion == max(getattr(w, f.name) for f in fields(w))


def test_spec_proposed_is_deliberately_just_below_spec_completion() -> None:
    gap = FitnessWeights().spec_completion - FitnessWeights().spec_proposed
    assert 0 < gap <= _INVARIANTS["spec_completion_above_spec_proposed_by_at_most"]


def test_code_quality_is_the_weakest_signal() -> None:
    w = FitnessWeights()
    assert w.code_quality == min(getattr(w, f.name) for f in fields(w))


# ─── composite calibration: literals, not the weights ───────────────────────
#
# Scorecard.composite is Σ(score·weight)/Σ(weight) over PRESENT signals, with
# any failed gate zeroing it. The calibration scenario below is the one the
# ladder exists for — a candidate that finished a contracted AC (score 1.0 at
# weight 0.45) against the same candidate having merely proposed a spec (1.0 at
# 0.40), both sharing a not-test-first red_green (0.5 at 0.14):
#   finished: (0.5*0.14 + 1.0*0.45) / (0.14 + 0.45) = 0.52/0.59
#   proposed: (0.5*0.14 + 1.0*0.40) / (0.14 + 0.40) = 0.47/0.54
# A 0.45 -> 0.40 swap (a subtle mutation sign tests absorb) inverts the order.


def _composite(weight_name: str) -> float:
    """Composite of the shared not-test-first baseline (red_green 0.5 @ 0.14)
    plus one perfect ladder signal at the weight under test."""
    return Scorecard(
        scores=[
            SignalScore("red_green", MeasureKind.CALCULATED, 0.5, 0.14, "not test-first"),
            SignalScore(
                weight_name,
                MeasureKind.CALCULATED,
                1.0,
                getattr(FitnessWeights(), weight_name),
                "ladder signal",
            ),
        ]
    ).composite


def test_composite_calibrates_the_ladder_ordering_with_literal_values() -> None:
    finished = _composite("spec_completion")
    proposed = _composite("spec_proposed")
    assert finished == pytest.approx(0.8814, abs=1e-4)
    assert proposed == pytest.approx(0.8704, abs=1e-4)
    assert finished > proposed


def test_a_failed_gate_zeroes_the_composite_whatever_the_weights() -> None:
    from maistro_evolve.scorecard import GateResult

    card = Scorecard(
        gates=[GateResult("tests_pass", False, "failed")],
        scores=[SignalScore("spec_completion", MeasureKind.CALCULATED, 1.0, 0.45, "x")],
    )
    assert card.composite == 0.0
    assert card.accepted is False
