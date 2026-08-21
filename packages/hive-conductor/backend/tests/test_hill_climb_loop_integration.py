"""End-to-end hill-climb loop trace: the accepted trajectory must reflect REAL gains only.

This exercises multiple evaluate_mutation passes and asserts that (a) above-noise gains
ratchet the recorded score up, and (b) within-noise blips do NOT ratchet — i.e. the loop
optimizes signal, not noise, after the noise-aware accept fix.

NOTE: this validates the optimizer mechanics, NOT human preference. There is currently no
closed-loop human-preference signal (blind champion-vs-challenger) wired into accept — the
loop optimizes the rubric number. Calibrating the rubric against revealed human preference
remains future work (see the eval-rigor discussion / a future SPEC).
"""

from __future__ import annotations

from services.hill_climber import HillClimber


def test_loop_ratchets_on_real_gains_only() -> None:
    hc = HillClimber(dag_id="d1", all_evals=["a", "b", "c", "d"], target_count=2, held_out_count=2)
    targets, held_out = ["a", "b"], ["c", "d"]
    base = {"a": 50, "b": 50, "c": 50, "d": 50}

    # Pass 1: real +8 gain on target 'a' → accepted, baseline advances.
    r1 = hc.evaluate_mutation(targets, held_out, base, {**base, "a": 58})
    assert r1.mutation_accepted is True
    base = {**base, "a": 58}

    # Pass 2: +3 noise blip on 'a' → rejected, baseline must NOT advance.
    r2 = hc.evaluate_mutation(targets, held_out, base, {**base, "a": 61})
    assert r2.mutation_accepted is False

    # Pass 3: real +7 gain → accepted.
    r3 = hc.evaluate_mutation(targets, held_out, base, {**base, "a": 65})
    assert r3.mutation_accepted is True

    # The recorded history for 'a' should reflect only real gains (58 then 65),
    # never the rejected 61 noise blip.
    recorded = [s.score for s in hc.score_history["a"]]
    assert 61 not in recorded
    assert recorded[-1] == 65
    # Net improvement equals the sum of REAL accepted gains, not noise.
    assert recorded[-1] - 50 == 15
