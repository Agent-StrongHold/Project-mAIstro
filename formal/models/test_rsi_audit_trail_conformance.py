"""Phase 16.5 item 3 (#342): audit-trail completeness for self-modification.

Property: every state transition that changes the active/promoted genome
has a corresponding audit log entry with a strictly increasing sequence
number and no gaps — and, since #342 closed the hole this model used to
merely observe, the converse holds too: a state change without its
immutable audit record cannot be constructed. The raw
``promote()``/``rollback()`` entrypoints are retired
(``promote_audited``/``rollback_audited`` are the only public path), an
audit sink that is down blocks the mutation outright, and a failed commit
entry compensates the mutation back.

Adversarial angles covered: an audit sink that fails mid-sequence (must
block or compensate the state mutation rather than let it through
silently), the absence of any alternate entrypoint that could bypass
``promote_audited``/``rollback_audited`` (asserted structurally — the raw
methods no longer exist on the public surface), a rejected promotion
(attempt recorded, no commit entry, no state change), tampering with the
recorded trail from outside (it is a copy of frozen entries), replaying
the committed entries alone to reconstruct the active genome, and randomly
interleaved failure injection across a long event sequence.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import Bundle, RuleBasedStateMachine, invariant, rule
from maistro_evolve.audit import GenomeAuditTrail
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


class _RecordingSink:
    async def log_delegation(self, peer_name: str, agent_id: str, detail: str) -> None:
        return None


class _FlakySink:
    """Fails every Nth call deterministically, to model an unreliable
    audit backend without relying on real randomness inside the rule."""

    def __init__(self, fail_every: int) -> None:
        self.fail_every = max(2, fail_every)
        self.calls = 0

    async def log_delegation(self, peer_name: str, agent_id: str, detail: str) -> None:
        self.calls += 1
        if self.calls % self.fail_every == 0:
            raise RuntimeError("flaky sink failure")


class _DeadSink:
    """Fails every call: an audit backend that is down."""

    async def log_delegation(self, peer_name: str, agent_id: str, detail: str) -> None:
        raise RuntimeError("audit sink down")


def _active_genome_id(store: PopulationStore) -> str | None:
    active = store.get_active()
    return active.id if active is not None else None


@given(
    fail_every=st.integers(min_value=2, max_value=11),
    op_count=st.integers(min_value=1, max_value=20),
)
@settings(max_examples=100)
def test_every_active_genome_change_has_a_gapless_audit_trail(fail_every, op_count):
    """Drives a sequence of audited promote/rollback calls through a sink
    that fails periodically, and confirms two things hold after every
    operation: (1) the audit trail's sequence numbers never have a gap,
    and (2) the active genome only ever changes in lockstep with a
    "_committed" entry being appended — never on its own."""
    import asyncio

    store = PopulationStore()
    sink = _FlakySink(fail_every)
    trail = GenomeAuditTrail(sink)

    next_id = 0
    last_active_id = None
    last_committed_count = 0

    async def run():
        nonlocal next_id, last_active_id, last_committed_count
        for i in range(op_count):
            do_promote = (i % 2 == 0) or store.get_active() is None
            try:
                if do_promote:
                    genome_id = f"g-{next_id}"
                    next_id += 1
                    store.add(_genome(genome_id))
                    await store.promote_audited(genome_id, trail)
                else:
                    await store.rollback_audited(trail)
            except RuntimeError:
                pass

            # Invariant 1: sequence numbers are exactly 1..N, no gaps.
            seqs = [e.sequence for e in trail.entries]
            assert seqs == list(range(1, len(seqs) + 1))

            # Invariant 2: the active genome only changes when a matching
            # "_committed" entry was appended in this same step.
            current_active_id = _active_genome_id(store)
            committed_count = sum(1 for e in trail.entries if e.event.endswith("_committed"))
            if current_active_id != last_active_id:
                assert committed_count > last_committed_count, (
                    f"active genome changed with no new committed audit entry (step {i}, do_promote={do_promote})"
                )
            last_active_id = current_active_id
            last_committed_count = committed_count

    asyncio.run(run())


class AuditedSelfModificationMachine(RuleBasedStateMachine):
    """Stateful model: only ``promote_audited``/``rollback_audited`` are
    exercised — and since #342 retired the raw entrypoints, they are the only
    methods that exist to exercise. This machine proves the audited path
    itself never lets state drift away from its audit trail, that the trail
    replays to the active genome, and that its sequence stays gapless; the
    companion test below proves the unaudited hole is unconstructible rather
    than merely detectable.
    """

    GenomeIds = Bundle("genome_ids")

    def __init__(self):
        super().__init__()
        self.store = PopulationStore()
        self.trail = GenomeAuditTrail(_RecordingSink())
        self.next_id = 0
        self.known_ids: list[str] = []

    def _run(self, coro):
        import asyncio

        return asyncio.run(coro)

    @rule(target=GenomeIds)
    def add_and_promote(self):
        genome_id = f"g-{self.next_id}"
        self.next_id += 1
        self.store.add(_genome(genome_id))
        self._run(self.store.promote_audited(genome_id, self.trail))
        self.known_ids.append(genome_id)
        return genome_id

    @rule()
    def rollback(self):
        self._run(self.store.rollback_audited(self.trail))

    @invariant()
    def committed_entries_never_outnumber_active_genome_changes(self):
        committed = [e for e in self.trail.entries if e.event.endswith("_committed")]
        # Every commit must reference a genome id we actually know about
        # (or empty string for "rolled back to nothing").
        for entry in committed:
            assert entry.genome_id == "" or entry.genome_id in self.known_ids

    @invariant()
    def sequence_is_gapless(self):
        seqs = [e.sequence for e in self.trail.entries]
        assert seqs == list(range(1, len(seqs) + 1))

    @invariant()
    def replaying_the_trail_reconstructs_the_active_genome(self):
        """Replay angle (#342): the committed entries alone are sufficient
        evidence of which genome is active — a promotion commit sets it, a
        rollback commit restores the target, and an empty rollback commit
        (nothing to roll back to) leaves it alone."""
        current: str | None = None
        for entry in self.trail.entries:
            if entry.event == "promotion_committed":
                current = entry.genome_id
            elif entry.event == "rollback_committed" and entry.genome_id:
                current = entry.genome_id
        assert current == _active_genome_id(self.store)


TestAuditedSelfModificationMachine = AuditedSelfModificationMachine.TestCase


def test_a_state_change_without_an_audit_record_cannot_land():
    """REPLACES the old "detectable gap" guard (#342), which asserted that
    calling promote()/rollback() directly moved the active genome while the
    audit trail stayed silent — and labeled that observable hole *expected*
    of the raw methods. The hole is closed from both sides:

    - structurally: the raw entrypoints are retired.
      ``promote_audited``/``rollback_audited`` are the only public
      promotion/rollback APIs, and the trail is a required argument of each,
      so an unaudited state change cannot be constructed — only forgotten.
    - behaviorally: an audit sink that is down blocks the mutation outright.
      Where the old test asserted ``after_entries == before_entries`` next
      to a changed active genome (state moved, audit silent — the enforced
      hole), the flipped assertions require the opposite: no state change,
      no committed record, the store untouched.

    This is the regression guard if a future change reintroduces a direct,
    unaudited call on the promotion path: it fails the moment a state
    change can happen without an immutable audit record again.
    """
    import asyncio
    import inspect

    # Structural: no public raw promotion/rollback entrypoint exists, and
    # every public one takes the audit trail as a required argument.
    assert not hasattr(PopulationStore, "promote")
    assert not hasattr(PopulationStore, "rollback")
    for name in ("promote_audited", "rollback_audited"):
        params = inspect.signature(getattr(PopulationStore, name)).parameters
        assert "audit" in params
        assert params["audit"].default is inspect.Parameter.empty

    # Behavioral: a dead audit sink cannot be routed around.
    store = PopulationStore()
    trail = GenomeAuditTrail(_DeadSink())
    store.add(_genome("g-blocked"))

    before_active = _active_genome_id(store)
    before_entries = len(trail.entries)

    with pytest.raises(RuntimeError, match="audit sink down"):
        asyncio.run(store.promote_audited("g-blocked", trail))

    assert _active_genome_id(store) == before_active
    assert store.get("g-blocked").is_active is False
    assert len(trail.entries) == before_entries


def test_a_rejected_promotion_is_audited_as_an_attempt_without_a_commit():
    """Rejection angle (#342): the approval gate refusing a genome is itself
    an auditable outcome — the attempt is recorded, no commit entry ever
    appears, and the state never moves."""
    import asyncio

    store = PopulationStore()
    trail = GenomeAuditTrail(_RecordingSink())
    store.add(_genome("g-unapproved", approved=False))

    with pytest.raises(PermissionError):
        asyncio.run(store.promote_audited("g-unapproved", trail))

    events = [(e.event, e.genome_id) for e in trail.entries]
    assert events == [("promotion_attempt", "g-unapproved")]
    assert _active_genome_id(store) is None


def test_recorded_entries_cannot_be_forged_or_erased_from_outside():
    """Tampering angle (#342): the trail's public surface is a copy of frozen
    entries — mutating what an outside caller can reach neither erases a
    record nor forges one, so replaying the trail stays trustworthy."""
    import asyncio

    store = PopulationStore()
    trail = GenomeAuditTrail(_RecordingSink())
    store.add(_genome("g-tamper"))
    asyncio.run(store.promote_audited("g-tamper", trail))
    recorded = [(e.sequence, e.event, e.genome_id) for e in trail.entries]

    trail.entries.clear()  # erasing through the returned list must not stick
    assert [(e.sequence, e.event, e.genome_id) for e in trail.entries] == recorded

    with pytest.raises(dataclasses.FrozenInstanceError):
        trail.entries[0].event = "promotion_forged"
    assert [(e.sequence, e.event, e.genome_id) for e in trail.entries] == recorded
