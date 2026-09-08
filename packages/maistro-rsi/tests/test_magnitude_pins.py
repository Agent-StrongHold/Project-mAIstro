"""#350 — magnitude pins for the RSI promotion-decision family.

The audit behind #350 showed that the promotion-path constants (regression-judge
cutoff, mutation-kill threshold, retained-diff fraction, free-router attempt
multiplier) survived large mutations because the existing tests assert only
direction, ordering, or the constant copied from the implementation.

Each constant here is pinned against an INDEPENDENTLY GOVERNED fixture
(`governed_magnitudes_rsi.json` in this directory) whose numbers are stated
apart from the implementation, plus boundary/calibration tests that use literal
expected values — never the production constant — so a mutation of the constant
cannot pass by dragging its own expectation along.

Two calibration scenarios additionally pin the promotion COMPOSITION end to
end: the fitness ladder ordering through ``compose_scorecard`` (finishing a
contracted AC must outrank proposing a new spec, with the exact composites the
ADR-070126-6386 v3 weights produce), so a subtle 0.45 -> 0.40 swap that a
sign test would absorb fails here.

No production values are changed by this file; it only pins them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from maistro_evolve.mutation_probe import MutationProbe
from maistro_rsi.candidate_fitness import (
    _DELETED_TRACE_CAP,
    _MUTATION_KILL_THRESHOLD,
    _MUTATION_MAX_MUTANTS,
    FitnessInputs,
    compose_scorecard,
)
from maistro_rsi.free_router import _pick_distinct
from maistro_rsi.regression_judge import (
    _MAX_DIFF_CHARS,
    _MIN_RETAINED_FRACTION,
    REJECT_BELOW,
    judge_regression_verdict,
)

_FIXTURE = json.loads(
    (Path(__file__).parent / "governed_magnitudes_rsi.json").read_text(encoding="utf-8")
)
_FX = _FIXTURE["entries"]


# ─── fixture conformance: the pin itself ────────────────────────────────────
#
# The fixture is the governed expectation; the production constant must match it
# exactly (or sit inside its governed range). This is what kills every magnitude
# mutation of the constant, large or subtle.


def test_reject_below_is_pinned_by_the_governed_fixture() -> None:
    assert _FX["regression_judge.REJECT_BELOW"]["value"] == REJECT_BELOW


def test_min_retained_fraction_is_pinned_by_the_governed_fixture() -> None:
    assert _FX["regression_judge._MIN_RETAINED_FRACTION"]["value"] == _MIN_RETAINED_FRACTION


def test_max_diff_chars_is_pinned_by_the_governed_fixture() -> None:
    assert _FX["regression_judge._MAX_DIFF_CHARS"]["value"] == _MAX_DIFF_CHARS


def test_mutation_kill_threshold_is_pinned_by_the_governed_fixture() -> None:
    assert _FX["candidate_fitness._MUTATION_KILL_THRESHOLD"]["value"] == _MUTATION_KILL_THRESHOLD


def test_mutation_max_mutants_is_within_its_governed_range() -> None:
    lo, hi = _FX["candidate_fitness._MUTATION_MAX_MUTANTS"]["range"]
    assert lo <= _MUTATION_MAX_MUTANTS <= hi


def test_deleted_trace_cap_is_within_its_governed_range() -> None:
    lo, hi = _FX["candidate_fitness._DELETED_TRACE_CAP"]["range"]
    assert lo <= _DELETED_TRACE_CAP <= hi


# ─── regression judge: verdict mapping and the fail-closed diff boundary ────


def _judge(score: float):
    """One judge consultation whose LLM always returns this score."""
    return judge_regression_verdict(
        "diff", "x.py", lambda messages, **k: {"content": f'{{"score": {score}}}'}
    )


def test_verdict_boundary_is_exactly_the_governed_cutoff() -> None:
    # 0.4 is 'pass'; one tick below is 'reject'. Literals, not REJECT_BELOW —
    # a mutated cutoff cannot pass by reading its own value back.
    assert _judge(0.4).status == "pass"
    assert _judge(0.3999).status == "reject"


def test_verdict_scores_ride_along_unguarded_by_the_cutoff() -> None:
    assert _judge(0.7).score == 0.7
    assert _judge(0.1).score == 0.1


def test_oversized_diff_boundary_is_exactly_twice_the_cap() -> None:
    # Retaining exactly half the diff (cap 8000, diff 16000) still rules;
    # one char more hides enough that the judge must refuse — fail closed (#307).
    exactly_half = judge_regression_verdict(
        "x" * 16000, "x.py", lambda *a, **k: {"content": '{"score": 0.9}'}
    )
    assert exactly_half.status == "pass"

    one_char_over = judge_regression_verdict("x" * 16001, "x.py", lambda *a, **k: ({}))
    assert one_char_over.status == "unavailable"
    assert one_char_over.score is None
    assert one_char_over.cause == "oversized_diff"


# ─── mutation gate: the anti-reward-hacking threshold boundary ──────────────


def _mutation_gate(probe: MutationProbe):
    card = compose_scorecard(FitnessInputs(tests_passed=True, mutation_probe=probe))
    return next(g for g in card.gates if g.name == "tests_pin_behavior")


def test_mutation_gate_passes_at_exactly_half_killed() -> None:
    gate = _mutation_gate(MutationProbe(available=True, total=1000, killed=500, survived=500))
    assert gate.passed is True


def test_mutation_gate_fails_one_kill_below_half() -> None:
    # 0.499 vs 0.5 — the subtle mutation a sign/ordering test absorbs.
    gate = _mutation_gate(MutationProbe(available=True, total=1000, killed=499, survived=501))
    assert gate.passed is False


def test_mutation_gate_rejects_a_quarter_killed_but_not_a_tenth_in_between() -> None:
    # Large-mutation kill: halving the threshold (0.5 -> 0.25) would pass 0.3.
    gate = _mutation_gate(MutationProbe(available=True, total=10, killed=3, survived=7))
    assert gate.passed is False


# ─── free router: the de-dup attempt multiplier ─────────────────────────────


def test_pick_distinct_stops_at_four_attempts_per_requested_pick() -> None:
    # A selector that keeps returning the SAME alias must stop after exactly
    # 4 x count attempts (count=3 -> 12 calls): the cap bounds live HTTP
    # resolution traffic per roster sentinel. A mutated multiplier (2, 40)
    # moves this count.
    calls = {"n": 0}

    def repeating_selector():
        calls["n"] += 1
        return "openrouter/same:free"

    picks = _pick_distinct(repeating_selector, 3)
    assert picks == ["openrouter/same:free"]
    assert calls["n"] == 12


def test_pick_distinct_needs_no_extra_attempts_when_picks_are_distinct() -> None:
    it = iter("abcdef")

    def cycling_selector():
        return next(it)

    assert _pick_distinct(cycling_selector, 3) == ["a", "b", "c"]


# ─── promotion composition: the fitness ladder ordering, end to end ─────────
#
# compose_scorecard renormalises over present signals, so the ladder's meaning
# shows up only in a composite comparison. Both scenarios share the identical
# baseline (a red_green 0.5 for a no-TDD-evidence diff); the only difference is
# finishing a contracted AC vs proposing a new spec. ADR-070126-6386 v3:
# finishing promised work (0.45, the largest weight in the system) must outrank
# proposing new work (0.40). Exact composites from those weights:
#   A: (0.5*0.14 + 1.0*0.45) / (0.14 + 0.45) = 0.52/0.59 = 0.8814
#   B: (0.5*0.14 + 1.0*0.40) / (0.14 + 0.40) = 0.47/0.54 = 0.8704


def test_finishing_a_contracted_ac_outranks_proposing_a_new_spec() -> None:
    finished = compose_scorecard(FitnessInputs(tests_passed=True, new_ac_ids=["SPEC-1/AC-1"]))
    proposed = compose_scorecard(FitnessInputs(tests_passed=True, proposed_spec_ids=["SPEC-9"]))
    assert finished.accepted and proposed.accepted
    assert finished.composite == pytest.approx(0.8814, abs=1e-4)
    assert proposed.composite == pytest.approx(0.8704, abs=1e-4)
    assert finished.composite > proposed.composite
