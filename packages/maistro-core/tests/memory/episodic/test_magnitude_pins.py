"""#350 — magnitude pins for episodic-memory dynamics (maistro-core).

Decay rates, boost/drop rates, promote/demote thresholds, tier weight bounds,
and the consolidation merge threshold decide what the system REMEMBERS and
FORGETS. Existing tests assert direction ("decay_rate < before"), ordering, or
the constant imported from the implementation — so magnitude mutations
survived: a FAST_DECAY of 1.2 instead of 2.0, a promote threshold of 50
instead of 5, or a REGRET floor of 0.06 instead of 0.6 all passed.

Every constant here is pinned against an INDEPENDENTLY GOVERNED fixture
(``governed_magnitudes_memory.json`` in this directory) whose numbers are
stated apart from the implementation, plus calibration/boundary tests that use
literal expected values — never the production constant — so a mutated
constant cannot pass by dragging its own expectation along.

The weighted-merge formula (merged weight = Σw²/Σw, biasing the survivor
toward the heavier memory) is calibrated with a literal value as well.

No production values are changed by this file; it only pins them.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from maistro.memory.episodic.consolidation import (
    apply_contradiction,
    consolidate,
)
from maistro.memory.episodic.tiers import on_feedback, reclassify, tick_decay
from maistro.memory.types import EpisodicMemory, MemoryScope, MemoryTier
from maistro.types.memory import (
    BOOST_RATE,
    CONTRADICT_DELTA,
    DEFAULT_DECAY_RATE,
    DROP_RATE,
    FAST_DECAY,
    REGRET_DEMOTE_THRESHOLD,
    REINFORCE_DELTA,
    SLOW_DECAY,
    WEIGHT_BOUNDS,
    WISDOM_PROMOTE_THRESHOLD,
)

_FIXTURE = json.loads(
    (Path(__file__).parent / "governed_magnitudes_memory.json").read_text(encoding="utf-8")
)
_FX = _FIXTURE["entries"]


def _mem(
    *,
    tier: MemoryTier = MemoryTier.OBSERVATION,
    weight: float = 0.3,
    reinforcement_count: int = 0,
    contradiction_count: int = 0,
    decay_rate: float = 0.01,
    hours_ago: float = 10.0,
) -> EpisodicMemory:
    return EpisodicMemory(
        memory_id="m1",
        tier=tier,
        weight=weight,
        content="c",
        scope=MemoryScope.AGENT,
        agent_id="a1",
        reinforcement_count=reinforcement_count,
        contradiction_count=contradiction_count,
        decay_rate=decay_rate,
        last_accessed_at=datetime.now(UTC) - timedelta(hours=hours_ago),
    )


# ─── fixture conformance: the pin itself ────────────────────────────────────


def test_decay_reinforce_constants_are_pinned_by_the_governed_fixture() -> None:
    expected = _FX["memory.decay_reinforce_constants"]["value"]
    assert expected["REINFORCE_DELTA"] == REINFORCE_DELTA
    assert expected["CONTRADICT_DELTA"] == CONTRADICT_DELTA
    assert expected["DEFAULT_DECAY_RATE"] == DEFAULT_DECAY_RATE
    assert expected["BOOST_RATE"] == BOOST_RATE
    assert expected["DROP_RATE"] == DROP_RATE
    assert expected["SLOW_DECAY"] == SLOW_DECAY
    assert expected["FAST_DECAY"] == FAST_DECAY


def test_promote_demote_thresholds_are_pinned_by_the_governed_fixture() -> None:
    expected = _FX["memory.promote_demote_thresholds"]["value"]
    assert expected["WISDOM_PROMOTE_THRESHOLD"] == WISDOM_PROMOTE_THRESHOLD
    assert expected["REGRET_DEMOTE_THRESHOLD"] == REGRET_DEMOTE_THRESHOLD


def test_weight_bounds_are_pinned_by_the_governed_fixture() -> None:
    expected = {
        MemoryTier[tier]: tuple(bounds)
        for tier, bounds in _FX["memory.WEIGHT_BOUNDS"]["value"].items()
    }
    assert expected == WEIGHT_BOUNDS


def test_similarity_merge_threshold_is_pinned_by_the_governed_fixture() -> None:
    from maistro.memory.episodic.consolidation import SIMILARITY_MERGE_THRESHOLD

    assert _FX["consolidation.SIMILARITY_MERGE_THRESHOLD"]["value"] == SIMILARITY_MERGE_THRESHOLD


# ─── calibration: literal scenario values, not the constants ────────────────
#
# SPEC-240's stated dynamics, computed by hand from the pinned constants:
# one thumbs-up  : weight +0.05*1.5 = +0.075, decay_rate *0.5
# one thumbs-down: weight -0.05*0.5 = -0.025, decay_rate *2.0
# one 10h tick   : weight -0.01*10  = -0.1


def test_one_thumbs_up_moves_weight_by_exactly_the_boost_delta() -> None:
    # LESSON bounds (0.5, 0.9): 0.6 + 0.075 = 0.675, inside — no clamp noise.
    result = on_feedback(_mem(tier=MemoryTier.LESSON, weight=0.6), "up")
    assert result.weight == pytest.approx(0.675)


def test_one_thumbs_down_moves_weight_by_exactly_the_drop_delta() -> None:
    result = on_feedback(_mem(tier=MemoryTier.LESSON, weight=0.6), "down")
    assert result.weight == pytest.approx(0.575)


def test_thumbs_up_halves_and_thumbs_down_doubles_the_decay_rate() -> None:
    up = on_feedback(_mem(decay_rate=0.01), "up")
    down = on_feedback(_mem(decay_rate=0.01), "down")
    assert up.decay_rate == pytest.approx(0.005)
    assert down.decay_rate == pytest.approx(0.02)


def test_ten_hour_tick_loses_exactly_the_default_rate_times_hours() -> None:
    # 0.3 - 0.01*10 = 0.2 (OBSERVATION floor 0.1 — no clamp). A doubled
    # DEFAULT_DECAY_RATE clamps to 0.1 and fails the literal.
    decayed = tick_decay(_mem(weight=0.3, decay_rate=0.01, hours_ago=10.0))
    assert decayed.weight == pytest.approx(0.2)


def test_feedback_stays_asymmetric_up_counts_three_times_down() -> None:
    # SPEC-240's boost:drop shape: +0.075 vs -0.025 per event — a 3:1 ratio.
    # Doubling BOOST_RATE or halving DROP_RATE breaks it.
    mem = _mem(tier=MemoryTier.LESSON, weight=0.6)
    gain = on_feedback(mem, "up").weight - mem.weight
    loss = mem.weight - on_feedback(mem, "down").weight
    assert gain == pytest.approx(3.0 * loss)


# ─── promote/demote boundaries: literal counts, not the thresholds ──────────


def test_four_ups_do_not_promote_but_five_do() -> None:
    assert reclassify(_mem(reinforcement_count=4)) != MemoryTier.WISDOM
    assert reclassify(_mem(reinforcement_count=5)) == MemoryTier.WISDOM


def test_four_downs_do_not_demote_but_five_do() -> None:
    assert reclassify(_mem(contradiction_count=4)) != MemoryTier.REGRET
    assert reclassify(_mem(contradiction_count=5)) == MemoryTier.REGRET


def test_fifth_consecutive_up_promotes_through_on_feedback() -> None:
    result = on_feedback(_mem(tier=MemoryTier.LESSON, reinforcement_count=4), "up")
    assert result.tier == MemoryTier.WISDOM


# ─── consolidation: merge boundary, contradiction delta, weighted merge ─────


def _pair(similarity: float):
    a = _mem(tier=MemoryTier.OPINION, weight=0.6)
    b = EpisodicMemory(
        memory_id="m2",
        tier=MemoryTier.OPINION,
        weight=0.4,
        content="c",
        scope=MemoryScope.AGENT,
        agent_id="a1",
    )
    result = consolidate(
        [a, b],
        similarity_fn=lambda x, y: similarity,
        contradiction_fn=lambda x, y: False,
    )
    return a, b, result


def test_merge_boundary_is_exactly_the_governed_threshold() -> None:
    # Default threshold (0.85): 0.85 similarity merges, 0.84 does not —
    # kills both a raised and a lowered bar.
    _, _, at_bar = _pair(0.85)
    assert len(at_bar.merges) == 1
    _, _, below_bar = _pair(0.84)
    assert below_bar.merges == []


def test_merged_weight_is_the_self_weighted_average_with_literal_value() -> None:
    # Σw²/Σw over {0.6, 0.4} = (0.36+0.16)/1.0 = 0.52 — biased toward the
    # heavier memory (a plain mean would say 0.5; Σw²/2Σw would say 0.26).
    a, b, result = _pair(0.9)
    assert result.merges[0].merged_weight == pytest.approx(0.52)
    assert result.merges[0].primary.memory_id == a.memory_id
    assert result.merges[0].absorbed[0].memory_id == b.memory_id


def test_contradiction_lowers_both_sides_by_exactly_the_pinned_delta() -> None:
    # CONTRADICT_DELTA 0.05: 0.6 -> 0.55 and 0.4 -> 0.35, both flagged for
    # review. A doubled delta (0.1) fails both literals.
    result = consolidate(
        [_mem(tier=MemoryTier.OPINION, weight=0.6), _mem(tier=MemoryTier.OPINION, weight=0.4)],
        similarity_fn=lambda x, y: 0.95,
        contradiction_fn=lambda x, y: True,
    )
    assert result.merges == []
    lo, hi = apply_contradiction(result.contradictions[0])
    weights = sorted((lo.weight, hi.weight))
    assert weights == [pytest.approx(0.35), pytest.approx(0.55)]
    assert lo.flagged_for_review and hi.flagged_for_review
    assert result.contradictions[0].confidence_delta == pytest.approx(0.05)
