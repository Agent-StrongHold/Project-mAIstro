"""Tests for episodic tiers, stores (ADR-016)."""

from __future__ import annotations

import pytest

from maistro.memory.episodic.store import InMemoryEpisodicStore
from maistro.memory.episodic.tiers import clamp_weight, decay, reinforce
from maistro.memory.types import EpisodicMemory, MemoryScope, MemoryTier


def _mem(
    mid: str = "m1",
    tier: MemoryTier = MemoryTier.OBSERVATION,
    weight: float = 0.3,
    content: str = "python import error fix",
    org_id: str = "org-1",
    team_id: str = "",
    agent_id: str | None = "agent-1",
    scope: MemoryScope = MemoryScope.AGENT,
    deleted: bool = False,
) -> EpisodicMemory:
    return EpisodicMemory(
        memory_id=mid,
        tier=tier,
        weight=weight,
        content=content,
        org_id=org_id,
        team_id=team_id,
        agent_id=agent_id,
        scope=scope,
        deleted=deleted,
    )


class TestClampWeight:
    def test_regret_floor_enforced(self) -> None:
        assert clamp_weight(MemoryTier.REGRET, 0.0) == pytest.approx(0.6)

    def test_wisdom_floor_enforced(self) -> None:
        assert clamp_weight(MemoryTier.WISDOM, 0.5) == pytest.approx(0.9)

    def test_observation_ceiling_enforced(self) -> None:
        assert clamp_weight(MemoryTier.OBSERVATION, 0.8) == pytest.approx(0.5)

    def test_within_bounds_unchanged(self) -> None:
        assert clamp_weight(MemoryTier.LESSON, 0.7) == pytest.approx(0.7)

    def test_all_tiers_clampable(self) -> None:
        for tier in MemoryTier:
            result = clamp_weight(tier, 0.5)
            assert 0.0 <= result <= 1.0


class TestReinforceDecay:
    def test_reinforce_increases_weight(self) -> None:
        mem = _mem(tier=MemoryTier.OPINION, weight=0.4)
        reinforced = reinforce(mem, delta=0.05)
        assert reinforced.weight > mem.weight

    def test_reinforce_increments_count(self) -> None:
        mem = _mem()
        reinforced = reinforce(mem)
        assert reinforced.reinforcement_count == mem.reinforcement_count + 1

    def test_reinforce_respects_ceiling(self) -> None:
        mem = _mem(tier=MemoryTier.OBSERVATION, weight=0.5)
        reinforced = reinforce(mem, delta=0.1)
        assert reinforced.weight == pytest.approx(0.5)

    def test_decay_decreases_weight(self) -> None:
        mem = _mem(tier=MemoryTier.OPINION, weight=0.6)
        decayed = decay(mem, delta=0.05)
        assert decayed.weight < mem.weight

    def test_decay_to_floor_for_regret(self) -> None:
        mem = _mem(tier=MemoryTier.REGRET, weight=0.6)
        decayed = decay(mem, delta=0.1)
        assert decayed.weight == pytest.approx(0.6)

    def test_decay_increments_contradiction_count(self) -> None:
        mem = _mem()
        decayed = decay(mem)
        assert decayed.contradiction_count == mem.contradiction_count + 1

    def test_reinforce_returns_new_object(self) -> None:
        mem = _mem()
        reinforced = reinforce(mem)
        assert reinforced is not mem


class TestInMemoryEpisodicStore:
    async def test_store_and_retrieve(self) -> None:
        store = InMemoryEpisodicStore()
        mem = _mem(content="python import error fix", agent_id="a1")
        await store.store(mem)
        results = await store.retrieve("python import", agent_id="a1")
        assert len(results) == 1
        assert results[0].memory_id == "m1"

    async def test_retrieve_no_match_returns_empty(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(_mem(content="docker build failure", agent_id="a1"))
        results = await store.retrieve("python error", agent_id="a1")
        assert results == []

    async def test_retrieve_excludes_deleted(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(_mem(content="important lesson", deleted=True))
        results = await store.retrieve("important", agent_id="agent-1")
        assert results == []

    async def test_retrieve_team_scope_requires_org(self) -> None:
        store = InMemoryEpisodicStore()
        mem = _mem(scope=MemoryScope.TEAM, team_id="alpha", org_id="org-A", content="team secret")
        await store.store(mem)
        # Caller in same team but different org
        results = await store.retrieve("team secret", team_id="alpha", org_id="org-B")
        assert results == []

    async def test_retrieve_team_correct_org(self) -> None:
        store = InMemoryEpisodicStore()
        mem = _mem(scope=MemoryScope.TEAM, team_id="alpha", org_id="org-A", content="team info")
        await store.store(mem)
        results = await store.retrieve("team info", team_id="alpha", org_id="org-A")
        assert len(results) == 1

    async def test_reinforce_updates_weight(self) -> None:
        store = InMemoryEpisodicStore()
        mem = _mem(tier=MemoryTier.OPINION, weight=0.4, agent_id="a1")
        await store.store(mem)
        await store.reinforce("m1", delta=0.1)
        results = await store.retrieve("python", agent_id="a1")
        assert results[0].weight > 0.4
