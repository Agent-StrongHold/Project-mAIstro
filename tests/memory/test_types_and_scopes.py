"""Tests for memory types, tiers, and scope filtering (ADR-013)."""

from __future__ import annotations

from maistro.memory.scopes import build_scope_filter, matches_scope
from maistro.memory.types import (
    WEIGHT_BOUNDS,
    EpisodicMemory,
    Learning,
    MemoryScope,
    MemoryTier,
    Outcome,
)


class TestWeightBounds:
    def test_regret_floor_is_0_6(self) -> None:
        lo, hi = WEIGHT_BOUNDS[MemoryTier.REGRET]
        assert lo == 0.6
        assert hi == 1.0

    def test_wisdom_floor_is_0_9(self) -> None:
        lo, hi = WEIGHT_BOUNDS[MemoryTier.WISDOM]
        assert lo == 0.9
        assert hi == 1.0

    def test_observation_ceiling_is_0_5(self) -> None:
        lo, hi = WEIGHT_BOUNDS[MemoryTier.OBSERVATION]
        assert lo == 0.1
        assert hi == 0.5

    def test_all_tiers_have_bounds(self) -> None:
        for tier in MemoryTier:
            assert tier in WEIGHT_BOUNDS


class TestBuildScopeFilter:
    def test_always_includes_global(self) -> None:
        filters = build_scope_filter()
        scopes = [f[0] for f in filters]
        assert MemoryScope.GLOBAL in scopes

    def test_includes_org_when_provided(self) -> None:
        filters = build_scope_filter(org_id="org-1")
        scopes = [f[0] for f in filters]
        assert MemoryScope.ORGANIZATION in scopes

    def test_no_org_no_org_filter(self) -> None:
        filters = build_scope_filter()
        scopes = [f[0] for f in filters]
        assert MemoryScope.ORGANIZATION not in scopes

    def test_includes_user_when_provided(self) -> None:
        filters = build_scope_filter(user_id="u-1")
        scopes = [f[0] for f in filters]
        assert MemoryScope.USER in scopes

    def test_includes_agent_when_provided(self) -> None:
        filters = build_scope_filter(agent_id="agent-1")
        scopes = [f[0] for f in filters]
        assert MemoryScope.AGENT in scopes


class TestMatchesScope:
    def _global_mem(self, org_id: str = "") -> EpisodicMemory:
        return EpisodicMemory(
            memory_id="m1",
            scope=MemoryScope.GLOBAL,
            content="x",
            tier=MemoryTier.OBSERVATION,
            weight=0.3,
            org_id=org_id,
        )

    def _team_mem(self, team_id: str, org_id: str) -> EpisodicMemory:
        return EpisodicMemory(
            memory_id="m2",
            scope=MemoryScope.TEAM,
            content="x",
            tier=MemoryTier.LESSON,
            weight=0.6,
            team_id=team_id,
            org_id=org_id,
        )

    def test_global_memory_visible_without_org(self) -> None:
        mem = self._global_mem()
        filters = build_scope_filter()
        assert matches_scope(mem, filters)

    def test_global_memory_different_org_blocked(self) -> None:
        mem = self._global_mem(org_id="org-A")
        # Caller is org-B
        filters = build_scope_filter(org_id="org-B")
        assert not matches_scope(mem, filters)

    def test_global_memory_same_org_visible(self) -> None:
        mem = self._global_mem(org_id="org-A")
        filters = build_scope_filter(org_id="org-A")
        assert matches_scope(mem, filters)

    def test_team_scope_requires_both_team_and_org(self) -> None:
        # Memory is in team "alpha" of org "org-A"
        mem = self._team_mem("alpha", "org-A")

        # Caller in same team but different org → should be blocked
        filters = build_scope_filter(team_id="alpha", org_id="org-B")
        assert not matches_scope(mem, filters)

    def test_team_scope_correct_team_and_org(self) -> None:
        mem = self._team_mem("alpha", "org-A")
        filters = build_scope_filter(team_id="alpha", org_id="org-A")
        assert matches_scope(mem, filters)


class TestLearningDataclass:
    def test_default_scope_is_agent(self) -> None:
        lr = Learning(learning="do X")
        assert lr.scope == MemoryScope.AGENT

    def test_default_hit_count(self) -> None:
        lr = Learning()
        assert lr.hit_count == 0

    def test_trigger_keys_default_empty(self) -> None:
        lr = Learning()
        assert lr.trigger_keys == []


class TestOutcomeDataclass:
    def test_default_success_true(self) -> None:
        o = Outcome()
        assert o.success is True

    def test_created_at_set(self) -> None:
        o = Outcome()
        assert o.created_at is not None
