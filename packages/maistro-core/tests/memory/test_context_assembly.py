"""Tests for ContextAssemblyPolicy (SPEC-244 / ADR-091)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import aiosqlite
import pytest

from maistro.agents.context_builder import ContextBuilder
from maistro.memory.context_assembly import DefaultContextAssemblyPolicy
from maistro.memory.episodic.store import InMemoryEpisodicStore
from maistro.memory.exposure import MemoryExposureMode
from maistro.memory.outcomes import InMemoryOutcomeStore
from maistro.memory.types import EpisodicMemory, MemoryScope, MemoryTier, Outcome
from maistro.memory.working.manager import WorkingMemoryManager
from maistro.persistence.sqlite_episodic import SqliteEpisodicStore
from maistro.projects.store import InMemoryProjectStore
from maistro.protocols.memory import EpisodicStore
from maistro.types.agent import AgentIdentity


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
        episodic_store=InMemoryEpisodicStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED),
        outcome_store=InMemoryOutcomeStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED),
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


@pytest.fixture(params=["memory", "sqlite", "memory-hot", "sqlite-hot"])
async def two_project_policy(
    request: pytest.FixtureRequest,
) -> AsyncIterator[DefaultContextAssemblyPolicy]:
    """One agent id with an AGENT-scope memory in each of Projects A and B.

    Exercise both stores directly and through the real working projection,
    hydrated from the same authoritative store, without mocked retrieval.
    """
    conn: aiosqlite.Connection | None = None
    store: EpisodicStore
    if request.param.startswith("sqlite"):
        conn = await aiosqlite.connect(":memory:")
        sqlite_store = SqliteEpisodicStore(conn, exposure_mode=MemoryExposureMode.AGENT_MANAGED)
        await sqlite_store.ensure_schema()
        store = sqlite_store
    else:
        store = InMemoryEpisodicStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED)
    for project, text in (("A", "alpha widget secret"), ("B", "beta widget plan")):
        memory = _mem(MemoryTier.OPINION, 0.5, memory_id=f"m-{project}", project_id=project)
        memory.content = text
        await store.store(memory)
    try:
        yield DefaultContextAssemblyPolicy(
            episodic_store=store,
            outcome_store=InMemoryOutcomeStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED),
            project_store=InMemoryProjectStore(),
            working_memory=(
                WorkingMemoryManager(workspace_id="ws-1", episodic_store=store)
                if request.param.endswith("-hot")
                else None
            ),
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

    @pytest.mark.parametrize("query", ["", "widget"])
    async def test_unattributed_global_is_not_promoted_into_a_project(
        self, two_project_policy: DefaultContextAssemblyPolicy, query: str
    ) -> None:
        memory = _mem(MemoryTier.WISDOM, 0.95, memory_id="global", project_id="")
        memory.scope = MemoryScope.GLOBAL
        memory.org_id = ""
        memory.content = "unattributed widget secret"
        await two_project_policy.episodic_store.store(memory)
        text = await two_project_policy.layer1("r1", "agent-1", "s1", query, project_id="B")
        assert "beta widget plan" in text
        assert "unattributed widget secret" not in text
        # The established empty-project contract still permits unbound globals.
        legacy = await two_project_policy.layer1("r1", "agent-1", "s1", query)
        assert "unattributed widget secret" in legacy

    @pytest.mark.parametrize("project_id", [" ", " B ", "missing"])
    @pytest.mark.parametrize("query", ["", "widget"])
    async def test_nonempty_project_is_an_exact_filter(
        self, two_project_policy: DefaultContextAssemblyPolicy, project_id: str, query: str
    ) -> None:
        # In particular, whitespace must never normalize to an unscoped read.
        text = await two_project_policy.layer1("r1", "agent-1", "s1", query, project_id=project_id)
        assert text == ""

    @pytest.mark.parametrize("query", ["", "widget"])
    async def test_project_filter_does_not_replace_agent_filter(
        self, two_project_policy: DefaultContextAssemblyPolicy, query: str
    ) -> None:
        text = await two_project_policy.layer1("r1", "another-agent", "s1", query, project_id="B")
        assert text == ""

    async def test_context_builder_preserves_layer1_project_scope(
        self, two_project_policy: DefaultContextAssemblyPolicy
    ) -> None:
        # Lowercase fixtures intentionally isolate Layer 1 from graph entities.
        # This pins prompt plumbing, not the separate Layer 4 visibility policy.
        class EmptyPrompts:
            async def get(self, name: str) -> str:
                return ""

        messages, _ = await ContextBuilder().build(
            [{"role": "user", "content": "widget"}],
            AgentIdentity(name="agent-1", model="m", soul_prompt_name="none"),
            prompt_manager=EmptyPrompts(),
            context_assembly_policy=two_project_policy,
            agent_id="agent-1",
            org_id="org-1",
            project_id="B",
        )
        assert messages[0]["role"] == "system"
        content = str(messages[0]["content"])
        assert "<maistro:memory>" in content
        assert "beta widget plan" in content
        assert "alpha widget secret" not in content
        if two_project_policy.working_memory is not None:
            assert two_project_policy.working_memory.projection().stats.records == 2


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


class AdaptiveContextAssemblyPolicy(DefaultContextAssemblyPolicy):
    """A policy that adapts the context budget based on query length."""

    async def assemble(
        self,
        project_id: str,
        run_id: str,
        agent_id: str,
        session_id: str,
        budget_tokens: int,
        query: str = "",
        org_id: str = "",
    ) -> str:
        # Adaptive logic: increase the budget for longer queries (a proxy for a
        # more complex task) and decrease it for very short ones. This is the
        # seam epic #901's "adaptive top-k/context budgeting" leaf would tune;
        # here it exists only to prove the budget actually reaches the
        # production inclusion decision.
        query_len = len(query)
        if query_len > 100:
            adaptive_budget = int(budget_tokens * 1.5)
        elif query_len < 10:
            adaptive_budget = int(budget_tokens * 0.5)
        else:
            adaptive_budget = budget_tokens
        # Ensure the budget is at least 1 to avoid errors.
        adaptive_budget = max(1, adaptive_budget)
        return await super().assemble(
            project_id=project_id,
            run_id=run_id,
            agent_id=agent_id,
            session_id=session_id,
            budget_tokens=adaptive_budget,
            query=query,
            org_id=org_id,
        )


class TestAdaptiveContextBudgeting:
    """Exploratory spike for epic #901's adaptive top-k/context budgeting.

    The assertions pin real ADR-091 behavior, not the scaffold policy: a
    memory below `ALWAYS_INCLUDE_WEIGHT` (0.6) is packed only while it fits
    whole, so a budget change is observable as an inclusion flip.
    """

    @staticmethod
    def _adaptive_policy() -> AdaptiveContextAssemblyPolicy:
        return AdaptiveContextAssemblyPolicy(
            episodic_store=InMemoryEpisodicStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED),
            outcome_store=InMemoryOutcomeStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED),
            project_store=InMemoryProjectStore(),
        )

    async def test_adaptive_budget_affects_inclusion_of_budget_dependent_memory(
        self,
    ) -> None:
        # "widget widget" estimates to 3 tokens and sits in the budget band
        # (weight 0.5 < ALWAYS_INCLUDE_WEIGHT), so it is included only while
        # it fits whole. Base budget 5: the short query's 0.5x factor leaves
        # 2 tokens (memory dropped); the long query's 1.5x leaves 7 (kept).
        # The query words overlap the content so the ranker keeps the memory
        # in the pool either way; only the budget decides.
        policy = self._adaptive_policy()
        project = await policy.project_store.create(
            owner_user_id="u1", name="Proj", profile_markdown=""
        )
        memory = _mem(MemoryTier.OPINION, 0.5, memory_id="m-budget", project_id=project.id)
        memory.content = "widget widget"
        await policy.episodic_store.store(memory)

        text_short = await policy.assemble(
            project_id=project.id,
            run_id="r1",
            agent_id="agent-1",
            session_id="s1",
            budget_tokens=5,
            query="widget",
        )
        text_long = await policy.assemble(
            project_id=project.id,
            run_id="r1",
            agent_id="agent-1",
            session_id="s1",
            budget_tokens=5,
            query="widget " + "x" * 100,
        )
        assert "widget widget" not in text_short
        assert "widget widget" in text_long

    async def test_short_query_reduction_is_what_drops_the_memory(
        self,
    ) -> None:
        # Control for the flip above: the default policy at the same base
        # budget keeps the memory for the very same short query, so the
        # exclusion is the adaptive 0.5x factor, not the base budget.
        policy = DefaultContextAssemblyPolicy(
            episodic_store=InMemoryEpisodicStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED),
            outcome_store=InMemoryOutcomeStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED),
            project_store=InMemoryProjectStore(),
        )
        project = await policy.project_store.create(
            owner_user_id="u1", name="Proj", profile_markdown=""
        )
        memory = _mem(MemoryTier.OPINION, 0.5, memory_id="m-budget", project_id=project.id)
        memory.content = "widget widget"
        await policy.episodic_store.store(memory)

        text = await policy.assemble(
            project_id=project.id,
            run_id="r1",
            agent_id="agent-1",
            session_id="s1",
            budget_tokens=5,
            query="widget",
        )
        assert "widget widget" in text

    async def test_budget_gate_includes_a_memory_only_while_it_fits_whole(
        self,
    ) -> None:
        # The gate any adaptive budgeting policy would tune, on the production
        # policy: a budget-band memory is dropped the moment it no longer
        # fits, while an always-include memory (weight >= 0.6) survives a
        # budget that drops it.
        policy = DefaultContextAssemblyPolicy(
            episodic_store=InMemoryEpisodicStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED),
            outcome_store=InMemoryOutcomeStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED),
            project_store=InMemoryProjectStore(),
        )
        project = await policy.project_store.create(
            owner_user_id="u1", name="Proj", profile_markdown=""
        )
        budgeted = _mem(MemoryTier.OPINION, 0.5, memory_id="m-budget", project_id=project.id)
        budgeted.content = "widget widget"
        await policy.episodic_store.store(budgeted)

        tight = await policy.assemble(
            project_id=project.id,
            run_id="r1",
            agent_id="agent-1",
            session_id="s1",
            budget_tokens=2,
        )
        assert tight == ""
        loose = await policy.assemble(
            project_id=project.id,
            run_id="r1",
            agent_id="agent-1",
            session_id="s1",
            budget_tokens=3,
        )
        assert loose == "widget widget"

        wisdom = _mem(MemoryTier.WISDOM, 0.95, memory_id="m-wisdom", project_id=project.id)
        wisdom.content = "wisdom lore"
        await policy.episodic_store.store(wisdom)
        with_wisdom = await policy.assemble(
            project_id=project.id,
            run_id="r1",
            agent_id="agent-1",
            session_id="s1",
            budget_tokens=2,
        )
        assert "wisdom lore" in with_wisdom
        assert "widget widget" not in with_wisdom
