"""compose_scorecard wiring for the diff-scoped mutation probe: an available
probe below the kill threshold vetoes promotion; at/above it passes and
contributes a score; an unavailable probe adds no gate at all. Pure (no
subprocess) — the probe object is constructed directly."""

from __future__ import annotations

from maistro_evolve.mutation_probe import MutationProbe
from maistro_rsi.candidate_fitness import FitnessInputs, compose_scorecard


def _base_inputs(probe: MutationProbe | None) -> FitnessInputs:
    # Everything else passing, so only the mutation gate is in question.
    return FitnessInputs(tests_passed=True, mutation_probe=probe)


def _gate(card: object, name: str):  # type: ignore[no-untyped-def]
    return next((g for g in card.gates if g.name == name), None)  # type: ignore[attr-defined]


def test_surviving_mutants_veto_promotion() -> None:
    probe = MutationProbe(available=True, total=4, killed=1, survived=3, survivors=["m.py:2"])
    card = compose_scorecard(_base_inputs(probe))
    gate = _gate(card, "tests_pin_behavior")
    assert gate is not None
    assert gate.passed is False  # 0.25 < 0.5 threshold
    assert card.accepted is False
    assert card.composite == 0.0  # a gate veto zeroes the composite


def test_mutants_killed_passes_gate_and_scores() -> None:
    probe = MutationProbe(available=True, total=4, killed=4, survived=0)
    card = compose_scorecard(_base_inputs(probe))
    gate = _gate(card, "tests_pin_behavior")
    assert gate is not None
    assert gate.passed is True
    assert card.accepted is True
    assert _gate(card, "tests_pin_behavior").detail["score"] == 1.0
    # The mutation_strength signal contributes to ranking on a passing card.
    assert any(s.name == "mutation_strength" for s in card.scores)


def test_threshold_boundary_passes() -> None:
    probe = MutationProbe(available=True, total=2, killed=1, survived=1)  # score 0.5
    card = compose_scorecard(_base_inputs(probe))
    assert _gate(card, "tests_pin_behavior").passed is True


def test_unavailable_probe_adds_no_gate() -> None:
    card = compose_scorecard(_base_inputs(MutationProbe(available=False)))
    assert _gate(card, "tests_pin_behavior") is None
    assert not any(s.name == "mutation_strength" for s in card.scores)
    assert card.accepted is True


def test_missing_probe_adds_no_gate() -> None:
    card = compose_scorecard(_base_inputs(None))
    assert _gate(card, "tests_pin_behavior") is None
    assert card.accepted is True
