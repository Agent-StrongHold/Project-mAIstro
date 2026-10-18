from __future__ import annotations

from datetime import UTC, datetime

import pytest

from maistro_evolve.audit import GenomeAuditTrail
from maistro_evolve.population import PopulationStore
from maistro_evolve.promotion import PromotionPolicy, PromotionRecord
from maistro_evolve.types import DAGTopology, EvalWeights, NodeGenome, PipelineGenome


def _genome(name: str, approved: bool = True) -> PipelineGenome:
    # Promotion now also requires measured capability evidence (#853), so the
    # fixture carries a real, gate-passing score; the capability gate itself is
    # exercised in test_rsi_safety.py's do-nothing promotion tests.
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
        eval_scores={"code_rsi": 0.6},
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
        approved_for_promotion=approved,
    )


def _stamped(
    name: str,
    score: float = 0.8,
    fitness: float | None = None,
    approved: bool = True,
    cycle: int = 1,
) -> PipelineGenome:
    """A genome carrying governed-promotion-eligible evidence (#854): repeated
    independent samples, stable spread, objective-stamped and current."""
    g = _genome(name, approved=approved)
    g.eval_scores = {"proxy_ifeval": score}
    g.fitness_score = fitness if fitness is not None else score
    g.harness_params["eval_samples"] = {"proxy_ifeval": 2}
    g.harness_params["eval_history"] = {"proxy_ifeval": [score - 0.01, score + 0.01]}
    g.harness_params["objective_version"] = "objective-test"
    g.harness_params["evidence_cycle"] = cycle
    return g


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
        store.add(_stamped("a"))
        trail = GenomeAuditTrail(_RecordingSink())

        genome = await store.promote_audited("g-a", trail)

        assert genome.is_active is True
        events = [(e.event, e.genome_id) for e in trail.entries]
        assert events == [("promotion_attempt", "g-a"), ("promotion_committed", "g-a")]
        assert [e.sequence for e in trail.entries] == [1, 2]
        # The committed entry carries the full immutable decision record (#854):
        # exact candidate/incumbent ids, objective version, evidence, decision
        # rule, approval, resulting active version.
        record = PromotionRecord.model_validate_json(trail.entries[-1].detail)
        assert record.candidate_id == "g-a"
        assert record.incumbent_id is None
        assert record.resulting_active_id == "g-a"
        assert record.approved is True
        assert record.objective_version == "objective-test"
        assert record.candidate_evidence["eval_samples"] == {"proxy_ifeval": 2}
        assert record.decision_rule["min_promotion_margin"] == (
            PromotionPolicy().min_promotion_margin
        )
        assert store.last_promotion_record is not None
        assert store.last_promotion_record.candidate_id == "g-a"

    @pytest.mark.asyncio
    async def test_promote_audited_rejection_is_recorded(self):
        """Unapproved AND unevaluated: the governed gate refuses, records the
        rejection (with reasons) after the attempt, and activates nothing."""
        store = PopulationStore()
        store.add(_genome("a", approved=False))
        trail = GenomeAuditTrail(_RecordingSink())

        with pytest.raises(PermissionError, match="governed promotion policy"):
            await store.promote_audited("g-a", trail)

        events = [e.event for e in trail.entries]
        assert events == ["promotion_attempt", "promotion_rejected"]
        assert "not approved for promotion" in trail.entries[-1].detail
        assert "not evaluated" in trail.entries[-1].detail
        assert store.get_active() is None

    @pytest.mark.asyncio
    async def test_promote_audited_failing_sink_blocks_state_mutation(self):
        store = PopulationStore()
        store.add(_stamped("a"))
        trail = GenomeAuditTrail(_FailingSink())

        with pytest.raises(RuntimeError, match="sink unavailable"):
            await store.promote_audited("g-a", trail)

        assert store.get_active() is None
        assert trail.entries == []

    @pytest.mark.asyncio
    async def test_promote_audited_failing_commit_log_compensates_to_no_active(self):
        store = PopulationStore()
        store.add(_stamped("a"))
        trail = GenomeAuditTrail(_FailOnNthCallSink(fail_on=2))

        with pytest.raises(RuntimeError, match="sink failed on commit"):
            await store.promote_audited("g-a", trail)

        assert store.get_active() is None
        assert store.get("g-a").is_active is False

    @pytest.mark.asyncio
    async def test_promote_audited_failing_commit_log_compensates_to_prior_active(self):
        store = PopulationStore()
        store.add(_stamped("a", score=0.3, fitness=0.5))
        store.add(_stamped("b", score=0.8, fitness=0.9))  # beats incumbent a by margin
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
        store.add(_stamped("a", score=0.3, fitness=0.5))
        store.add(_stamped("b", score=0.8, fitness=0.9))
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
        store.add(_stamped("a"))
        await store.promote_audited("g-a", trail)

        restored = await store.rollback_audited(trail)

        assert restored is None
        tail_events = [(e.event, e.genome_id) for e in trail.entries[-2:]]
        assert tail_events == [("rollback_attempt", "g-a"), ("rollback_committed", "")]

    @pytest.mark.asyncio
    async def test_rollback_audited_failing_sink_blocks_state_mutation(self):
        store = PopulationStore()
        good_trail = GenomeAuditTrail(_RecordingSink())
        store.add(_stamped("a", score=0.3, fitness=0.5))
        store.add(_stamped("b", score=0.8, fitness=0.9))
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
        store.add(_stamped("a", score=0.3, fitness=0.5))
        store.add(_stamped("b", score=0.8, fitness=0.9))
        await store.promote_audited("g-a", good_trail)
        await store.promote_audited("g-b", good_trail)

        bad_trail = GenomeAuditTrail(_FailOnNthCallSink(fail_on=2))
        with pytest.raises(RuntimeError, match="sink failed on commit"):
            await store.rollback_audited(bad_trail)

        active = store.get_active()
        assert active is not None
        assert active.id == "g-b"
        assert store.get("g-a").is_active is False
