"""Tests for ContextAssemblyPolicy (SPEC-244 / ADR-091)."""

from __future__ import annotations

import pytest

from maistro.memory.context_assembly import DefaultContextAssemblyPolicy
from maistro.memory.episodic.store import InMemoryEpisodicStore
from maistro.memory.outcomes import InMemoryOutcomeStore
from maistro.memory.types import EpisodicMemory, MemoryScope, MemoryTier
from maistro.projects.store import InMemoryProjectStore


def _mem(
    tier: MemoryTier, weight: float, memory_id: str = "m1", project_id: str = "p1"
) -> EpisodicMemory:
    return EpisodicMemory(
        memory_id=memory_id,
        tier=tier,
        weight=weight,
        content="some content",
        org_id="org-1",
        team_id="team-1",
        agent_id="agent-1",
        scope=MemoryScope.AGENT,
        project_id=project_id,
    )


@pytest.fixture
def policy() -> DefaultContextAssemblyPolicy:
    return DefaultContextAssemblyPolicy(
        episodic_store=InMemoryEpisodicStore(),
        outcome_store=InMemoryOutcomeStore(),
        project_store=InMemoryProjectStore(),
    )


class TestLayer0:
    async def test_returns_profile_markdown(self, policy: DefaultContextAssemblyPolicy) -> None:
        project = await policy.project_store.create(
            owner_user_id="u1", name="Proj", profile_markdown="Build a rocket."
        )
        text = await policy.layer0(project.id)
        assert text == "Build a rocket."

    async def test_unknown_project_returns_empty(
        self, policy: DefaultContextAssemblyPolicy
    ) -> None:
        text = await policy.layer0("does-not-exist")
        assert text == ""


class TestLayer1:
    async def test_includes_wisdom_unconditionally(
        self, policy: DefaultContextAssemblyPolicy
    ) -> None:
        await policy.episodic_store.store(_mem(MemoryTier.WISDOM, 0.95))
        text = await policy.layer1(run_id="r1", agent_id="agent-1", session_id="s1")
        assert "some content" in text

    async def test_excludes_low_weight_observation(
        self, policy: DefaultContextAssemblyPolicy
    ) -> None:
        await policy.episodic_store.store(_mem(MemoryTier.OBSERVATION, 0.2))
        text = await policy.layer1(run_id="r1", agent_id="agent-1", session_id="s1")
        assert text == ""

    async def test_includes_mid_weight_opinion(self, policy: DefaultContextAssemblyPolicy) -> None:
        await policy.episodic_store.store(_mem(MemoryTier.OPINION, 0.5))
        text = await policy.layer1(run_id="r1", agent_id="agent-1", session_id="s1")
        assert "some content" in text


class TestLayer2:
    async def test_returns_empty_placeholder(self, policy: DefaultContextAssemblyPolicy) -> None:
        text = await policy.layer2(session_id="s1", budget_tokens=1000)
        assert text == ""


class TestLayer3:
    async def test_excludes_non_wisdom_episodic(self, policy: DefaultContextAssemblyPolicy) -> None:
        await policy.episodic_store.store(_mem(MemoryTier.LESSON, 0.8))
        text = await policy.layer3(project_id="p1")
        assert "some content" not in text

    async def test_includes_wisdom_episodic(self, policy: DefaultContextAssemblyPolicy) -> None:
        await policy.episodic_store.store(_mem(MemoryTier.WISDOM, 0.95))
        text = await policy.layer3(project_id="p1")
        assert "some content" in text


class TestLayer4:
    async def test_returns_empty_placeholder(self, policy: DefaultContextAssemblyPolicy) -> None:
        text = await policy.layer4(project_id="p1")
        assert text == ""


class TestAssemble:
    async def test_concatenates_layers_in_order(self, policy: DefaultContextAssemblyPolicy) -> None:
        project = await policy.project_store.create(
            owner_user_id="u1", name="Proj", profile_markdown="CONSTRAINTS"
        )
        await policy.episodic_store.store(_mem(MemoryTier.WISDOM, 0.95))
        text = await policy.assemble(
            project_id=project.id,
            run_id="r1",
            agent_id="agent-1",
            session_id="s1",
            budget_tokens=10_000,
        )
        assert text.index("CONSTRAINTS") < text.index("some content")

    async def test_layer0_never_truncated_even_under_tight_budget(
        self, policy: DefaultContextAssemblyPolicy
    ) -> None:
        project = await policy.project_store.create(
            owner_user_id="u1", name="Proj", profile_markdown="CONSTRAINTS" * 50
        )
        text = await policy.assemble(
            project_id=project.id,
            run_id="r1",
            agent_id="agent-1",
            session_id="s1",
            budget_tokens=1,
        )
        assert "CONSTRAINTS" * 50 in text
