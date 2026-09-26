"""Tests for ContextAssemblyPolicy (SPEC-244 / ADR-091)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import aiosqlite
import pytest

from maistro.memory.context_assembly import DefaultContextAssemblyPolicy
from maistro.memory.episodic.store import InMemoryEpisodicStore
from maistro.memory.outcomes import InMemoryOutcomeStore
from maistro.memory.types import EpisodicMemory, MemoryScope, MemoryTier, Outcome
from maistro.persistence.sqlite_episodic import SqliteEpisodicStore
from maistro.projects.store import InMemoryProjectStore
from maistro.protocols.memory import EpisodicStore


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


@pytest.fixture(params=["memory", "sqlite"])
async def two_project_policy(
    request: pytest.FixtureRequest,
) -> AsyncIterator[DefaultContextAssemblyPolicy]:
    """One agent id with an AGENT-scope memory in each of Projects A and B.

    Parametrized over the in-memory and SQLite stores so the project filter is
    shown on a durable backend too, not only on the one that keeps objects.
    """
    conn: aiosqlite.Connection | None = None
    store: EpisodicStore
    if request.param == "sqlite":
        conn = await aiosqlite.connect(":memory:")
        sqlite_store = SqliteEpisodicStore(conn)
        await sqlite_store.ensure_schema()
        store = sqlite_store
    else:
        store = InMemoryEpisodicStore()
    for project, text in (("A", "alpha widget secret"), ("B", "beta widget plan")):
        memory = _mem(MemoryTier.OPINION, 0.5, memory_id=f"m-{project}", project_id=project)
        memory.content = text
        await store.store(memory)
    try:
        yield DefaultContextAssemblyPolicy(
            episodic_store=store,
            outcome_store=InMemoryOutcomeStore(),
            project_store=InMemoryProjectStore(),
        )
    finally:
        if conn is not None:
            await conn.close()


class TestLayer1IsProjectScoped:
    """An agent id reused across Projects must not recall the other Project's memory (#1047)."""

    @pytest.mark.parametrize("query", ["", "widget"])
    async def test_assemble_recalls_only_the_current_projects_memory(
        self, two_project_policy: DefaultContextAssemblyPolicy, query: str
    ) -> None:
        text = await two_project_policy.assemble(
            project_id="B",
            run_id="r1",
            agent_id="agent-1",
            session_id="s1",
            budget_tokens=10_000,
            query=query,
        )
        assert "beta widget plan" in text
        assert "alpha widget secret" not in text

    @pytest.mark.parametrize("query", ["", "widget"])
    async def test_blank_project_keeps_the_agent_wide_recall(
        self, two_project_policy: DefaultContextAssemblyPolicy, query: str
    ) -> None:
        text = await two_project_policy.layer1(
            run_id="r1", agent_id="agent-1", session_id="s1", query=query
        )
        assert "alpha widget secret" in text
        assert "beta widget plan" in text

    @pytest.mark.parametrize("query", ["", "widget"])
    async def test_unattributed_memory_is_not_guessed_into_a_project(
        self, policy: DefaultContextAssemblyPolicy, query: str
    ) -> None:
        await policy.episodic_store.store(
            _mem(MemoryTier.OPINION, 0.5, memory_id="m-none", project_id="")
        )
        text = await policy.layer1(
            run_id="r1", agent_id="agent-1", session_id="s1", query=query, project_id="B"
        )
        assert text == ""


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
    async def test_missing_org_does_not_inject_global_outcome_context(
        self, policy: DefaultContextAssemblyPolicy
    ) -> None:
        await policy.outcome_store.record(
            Outcome(
                task_type="",
                success=False,
                error_type="secret-org-a",
                org_id="org-a",
                project_id="p1",
            )
        )

        text = await policy.assemble(
            project_id="p1",
            run_id="r1",
            agent_id="agent-1",
            session_id="s1",
            budget_tokens=10_000,
        )

        assert "secret-org-a" not in text

    async def test_concatenates_layers_in_order(self, policy: DefaultContextAssemblyPolicy) -> None:
        project = await policy.project_store.create(
            owner_user_id="u1", name="Proj", profile_markdown="CONSTRAINTS"
        )
        await policy.episodic_store.store(_mem(MemoryTier.WISDOM, 0.95, project_id=project.id))
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
