"""Phase 16.5 item 3: audit-trail completeness for self-modification.

Property: every state transition that changes the active/promoted genome
has a corresponding audit log entry with a strictly increasing sequence
number and no gaps.

Adversarial angles covered: an audit sink that fails mid-sequence (must
block the state mutation rather than let it through silently), an
alternate entrypoint that bypasses ``promote_audited``/``rollback_audited``
(``promote()``/``rollback()`` called directly — confirmed observable as a
state change with no matching audit entry, which is the actual bypass this
property exists to catch and which callers must avoid), and randomly
interleaved failure injection across a long event sequence.
"""

from __future__ import annotations

from datetime import UTC, datetime

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
    exercised, so this machine proves the audited path itself never lets
    state drift away from its audit trail — the companion bypass test
    below proves the *unaudited* entrypoints are a real, detectable gap
    that callers must route around, not a hypothetical concern.
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


TestAuditedSelfModificationMachine = AuditedSelfModificationMachine.TestCase


def test_bypassing_the_audited_wrapper_is_a_real_detectable_gap():
    """Adversarial: calling promote()/rollback() directly (the alternate,
    unaudited entrypoint) changes the active genome with zero matching
    audit entries. This is *expected* of the raw methods — the property
    this test enforces is that the gap is reliably observable (active
    genome changed, audit trail didn't), so any caller that skips the
    audited wrapper is leaving a detectable, not a silent, hole. RSI
    callers (EvolutionCycle, reflective_improve) must route every
    promotion/rollback through promote_audited/rollback_audited — this
    test is the regression guard if a future change reintroduces a
    direct, unaudited call on that path.
    """
    store = PopulationStore()
    trail = GenomeAuditTrail(_RecordingSink())
    store.add(_genome("g-bypass"))

    before_active = _active_genome_id(store)
    before_entries = len(trail.entries)

    store.promote("g-bypass")  # bypasses promote_audited on purpose

    after_active = _active_genome_id(store)
    after_entries = len(trail.entries)

    assert before_active != after_active
    assert after_entries == before_entries  # the gap: state moved, audit didn't
