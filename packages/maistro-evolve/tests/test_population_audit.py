from __future__ import annotations

from datetime import UTC, datetime

import pytest

from maistro_evolve.audit import GenomeAuditTrail
from maistro_evolve.population import PopulationStore
from maistro_evolve.types import DAGTopology, EvalWeights, NodeGenome, PipelineGenome


def _genome(name: str, approved: bool = True) -> PipelineGenome:
    return PipelineGenome(
        id=f"g-{name}",
        name=name,
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
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def log_delegation(self, peer_name: str, agent_id: str, detail: str) -> None:
        self.calls.append((peer_name, agent_id, detail))


class _FailingSink:
    async def log_delegation(self, peer_name: str, agent_id: str, detail: str) -> None:
        raise RuntimeError("sink unavailable")


class _FailOnNthCallSink:
    def __init__(self, fail_on: int) -> None:
        self.fail_on = fail_on
        self.calls = 0

    async def log_delegation(self, peer_name: str, agent_id: str, detail: str) -> None:
        self.calls += 1
        if self.calls == self.fail_on:
            raise RuntimeError("sink failed on commit")


class TestPromoteAudited:
    @pytest.mark.asyncio
    async def test_promote_audited_logs_attempt_then_commit(self):
        store = PopulationStore()
        store.add(_genome("a"))
        trail = GenomeAuditTrail(_RecordingSink())

        genome = await store.promote_audited("g-a", trail)

        assert genome.is_active is True
        events = [(e.event, e.genome_id) for e in trail.entries]
        assert events == [("promotion_attempt", "g-a"), ("promotion_committed", "g-a")]
        assert [e.sequence for e in trail.entries] == [1, 2]

    @pytest.mark.asyncio
    async def test_promote_audited_failing_promotion_logs_only_attempt(self):
        store = PopulationStore()
        store.add(_genome("a", approved=False))
        trail = GenomeAuditTrail(_RecordingSink())

        with pytest.raises(PermissionError):
            await store.promote_audited("g-a", trail)

        events = [e.event for e in trail.entries]
        assert events == ["promotion_attempt"]
        assert store.get_active() is None

    @pytest.mark.asyncio
    async def test_promote_audited_failing_sink_blocks_state_mutation(self):
        store = PopulationStore()
        store.add(_genome("a"))
        trail = GenomeAuditTrail(_FailingSink())

        with pytest.raises(RuntimeError, match="sink unavailable"):
            await store.promote_audited("g-a", trail)

        assert store.get_active() is None
        assert trail.entries == []

    @pytest.mark.asyncio
    async def test_promote_audited_failing_commit_log_compensates_to_no_active(self):
        store = PopulationStore()
        store.add(_genome("a"))
        trail = GenomeAuditTrail(_FailOnNthCallSink(fail_on=2))

        with pytest.raises(RuntimeError, match="sink failed on commit"):
            await store.promote_audited("g-a", trail)

        assert store.get_active() is None
        assert store.get("g-a").is_active is False

    @pytest.mark.asyncio
    async def test_promote_audited_failing_commit_log_compensates_to_prior_active(self):
        store = PopulationStore()
        store.add(_genome("a"))
        store.add(_genome("b"))
        good_trail = GenomeAuditTrail(_RecordingSink())
        await store.promote_audited("g-a", good_trail)

        bad_trail = GenomeAuditTrail(_FailOnNthCallSink(fail_on=2))
        with pytest.raises(RuntimeError, match="sink failed on commit"):
            await store.promote_audited("g-b", bad_trail)

        active = store.get_active()
        assert active is not None
        assert active.id == "g-a"
        assert store.get("g-b").is_active is False


class TestRollbackAudited:
    @pytest.mark.asyncio
    async def test_rollback_audited_logs_attempt_then_commit(self):
        store = PopulationStore()
        trail = GenomeAuditTrail(_RecordingSink())
        store.add(_genome("a"))
        store.add(_genome("b"))
        await store.promote_audited("g-a", trail)
        await store.promote_audited("g-b", trail)

        restored = await store.rollback_audited(trail)

        assert restored is not None
        assert restored.id == "g-a"
        tail_events = [(e.event, e.genome_id) for e in trail.entries[-2:]]
        assert tail_events == [("rollback_attempt", "g-b"), ("rollback_committed", "g-a")]
        assert [e.sequence for e in trail.entries] == [1, 2, 3, 4, 5, 6]

    @pytest.mark.asyncio
    async def test_rollback_audited_with_nothing_to_roll_back_to_logs_none(self):
        store = PopulationStore()
        trail = GenomeAuditTrail(_RecordingSink())
        store.add(_genome("a"))
        await store.promote_audited("g-a", trail)

        restored = await store.rollback_audited(trail)

        assert restored is None
        tail_events = [(e.event, e.genome_id) for e in trail.entries[-2:]]
        assert tail_events == [("rollback_attempt", "g-a"), ("rollback_committed", "")]

    @pytest.mark.asyncio
    async def test_rollback_audited_failing_sink_blocks_state_mutation(self):
        store = PopulationStore()
        good_trail = GenomeAuditTrail(_RecordingSink())
        store.add(_genome("a"))
        store.add(_genome("b"))
        await store.promote_audited("g-a", good_trail)
        await store.promote_audited("g-b", good_trail)

        failing_trail = GenomeAuditTrail(_FailingSink())
        with pytest.raises(RuntimeError, match="sink unavailable"):
            await store.rollback_audited(failing_trail)

        active = store.get_active()
        assert active is not None
        assert active.id == "g-b"

    @pytest.mark.asyncio
    async def test_rollback_audited_failing_commit_log_compensates_active_genome(self):
        store = PopulationStore()
        good_trail = GenomeAuditTrail(_RecordingSink())
        store.add(_genome("a"))
        store.add(_genome("b"))
        await store.promote_audited("g-a", good_trail)
        await store.promote_audited("g-b", good_trail)

        bad_trail = GenomeAuditTrail(_FailOnNthCallSink(fail_on=2))
        with pytest.raises(RuntimeError, match="sink failed on commit"):
            await store.rollback_audited(bad_trail)

        active = store.get_active()
        assert active is not None
        assert active.id == "g-b"
        assert store.get("g-a").is_active is False
