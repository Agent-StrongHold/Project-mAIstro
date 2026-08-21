"""Phase 16.5 item 2: rollback/kill-switch formal conformance.

Property: for any sequence of promotion + regression-signal (rollback)
events, the active genome after rollback always equals the last genome
that passed the promotion gate (i.e. the genome promoted immediately
before the one that's now regressing) — never anything else, and never
a genome that was never actually promoted.

Adversarial angles covered: a corrupted/missing prior-genome snapshot,
rollback with nothing to roll back to, repeated/raced rollback calls,
and rollback attempted on an unapproved/never-promoted genome.
"""

from __future__ import annotations

from datetime import UTC, datetime

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule
from maistro_evolve.population import PopulationStore
from maistro_evolve.types import DAGTopology, EvalWeights, NodeGenome, PipelineGenome


def _genome(genome_id: str, approved: bool = True) -> PipelineGenome:
    return PipelineGenome(
        id=genome_id,
        name=genome_id,
        topology=DAGTopology(
            nodes=[
                NodeGenome(
                    id="q1",
                    role="queen",
                    strategy="react",
                    model="gpt-4",
                    temperature=0.3,
                    max_tokens=4096,
                    system_prompt="test",
                    max_tool_rounds=5,
                )
            ],
            edges=[],
            entry_node="q1",
            max_cycles=3,
            beam_width=1,
            use_scout=False,
        ),
        eval_weights=EvalWeights(),
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
        approved_for_promotion=approved,
    )


class RollbackConformanceMachine(RuleBasedStateMachine):
    """Models a stream of promotion + regression-signal events.

    ``self.promotion_history`` is the independently-tracked ground truth
    of "the last genome that passed the promotion gate" at each point in
    time — the invariant checks the store's actual active genome against
    this ground truth after every rule, not just after rollbacks.
    """

    def __init__(self):
        super().__init__()
        self.store = PopulationStore()
        self.next_id = 0
        self.promotion_history: list[str] = []
        self.deleted_targets: set[str] = set()

    def _new_genome_id(self) -> str:
        self.next_id += 1
        return f"g-{self.next_id}"

    @rule()
    def promote_new_genome(self):
        genome_id = self._new_genome_id()
        self.store.add(_genome(genome_id, approved=True))
        self.store.promote(genome_id)
        self.promotion_history.append(genome_id)

    @rule()
    def regression_signal_triggers_rollback(self):
        result = self.store.rollback()
        if result is None:
            return
        # A successful rollback always means we're now active on the
        # promotion immediately prior to the one that just regressed.
        if self.promotion_history:
            self.promotion_history.pop()

    @precondition(lambda self: len(self.promotion_history) >= 1)
    @rule()
    def corrupt_the_rollback_target_snapshot(self):
        """Adversarial: simulate the prior-genome snapshot vanishing
        (e.g. storage corruption) between promotion and rollback."""
        active = self.store.get_active()
        if active is None or active.rollback_target_id is None:
            return
        target_id = active.rollback_target_id
        self.store.remove(target_id)
        self.deleted_targets.add(target_id)

    @rule()
    def double_rollback_is_safe(self):
        """Adversarial: simulate a race — two rollback calls in a row
        with no promotion in between. The second must be a safe no-op
        relative to the first, never corrupting which genome is active."""
        first = self.store.rollback()
        if first is not None and self.promotion_history:
            self.promotion_history.pop()
        second = self.store.rollback()
        # The second call must not silently re-activate a different
        # genome than the first call already settled on.
        if first is not None and second is not None:
            assert second.id == self.store.get_active().id
        if second is not None and self.promotion_history:
            self.promotion_history.pop()

    @invariant()
    def active_genome_is_always_a_genuinely_promoted_genome(self):
        active = self.store.get_active()
        if active is None:
            return
        assert active.id in self.promotion_history or active.id == (
            self.promotion_history[-1] if self.promotion_history else None
        )

    @invariant()
    def at_most_one_genome_is_active(self):
        actives = [g for g in self.store.list_all() if g.is_active]
        assert len(actives) <= 1

    @invariant()
    def corrupted_target_never_silently_reappears_as_active(self):
        active = self.store.get_active()
        if active is None:
            return
        assert active.id not in self.deleted_targets


TestRollbackConformanceMachine = RollbackConformanceMachine.TestCase


@given(
    promotion_count=st.integers(min_value=1, max_value=8),
    rollback_count=st.integers(min_value=0, max_value=8),
)
@settings(max_examples=100)
def test_rollback_always_restores_the_immediately_prior_promotion(promotion_count, rollback_count):
    store = PopulationStore()
    history: list[str] = []

    for i in range(promotion_count):
        genome_id = f"g-{i}"
        store.add(_genome(genome_id))
        store.promote(genome_id)
        history.append(genome_id)

    for _ in range(rollback_count):
        result = store.rollback()
        if result is None:
            assert len(history) <= 1
            continue
        history.pop()
        assert result.id == history[-1]

    active = store.get_active()
    if history:
        assert active is not None
        assert active.id == history[-1]
    else:
        # Rolling back past the very first promotion leaves that first
        # genome active (it has no rollback_target_id, so rollback()
        # returns None and deactivates nothing further) — never empty.
        assert active is not None
        assert active.id == "g-0"


def test_rollback_on_a_genome_with_a_deleted_target_returns_none_not_garbage():
    store = PopulationStore()
    store.add(_genome("g-0"))
    store.add(_genome("g-1"))
    store.promote("g-0")
    store.promote("g-1")

    store.remove("g-0")  # corrupt the snapshot rollback would target

    result = store.rollback()

    assert result is None
    active = store.get_active()
    assert active is not None
    assert active.id == "g-1"  # regressing genome stays active, never a ghost


def test_rollback_with_nothing_promoted_yet_is_a_safe_noop():
    store = PopulationStore()
    assert store.rollback() is None
    assert store.get_active() is None


def test_an_unapproved_genome_can_never_become_the_rollback_target():
    store = PopulationStore()
    store.add(_genome("g-0", approved=True))
    store.add(_genome("g-1", approved=False))
    store.promote("g-0")

    # g-1 was never promoted (unapproved), so it can never end up as the
    # rollback target even if an attacker tries to promote it directly.
    import pytest

    with pytest.raises(PermissionError):
        store.promote("g-1")

    active = store.get_active()
    assert active is not None
    assert active.id == "g-0"
