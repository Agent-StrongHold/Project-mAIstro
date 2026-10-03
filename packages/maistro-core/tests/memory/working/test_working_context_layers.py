"""Layer 1 / Layer 4 wiring through the working-memory projection (issue #301).

The acceptance line these tests exist for: `DefaultContextAssemblyPolicy.layer4()`
returns real graph-backed context for a populated Workspace instead of the
placeholder `""`, and Layer 1 goes through the indexed hot projection when one
is wired — while scope visibility and canonical provenance survive the hop,
and every degradation falls back to the durable path loudly.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.memory.context_assembly import DefaultContextAssemblyPolicy
from maistro.memory.episodic.store import InMemoryEpisodicStore
from maistro.memory.outcomes import InMemoryOutcomeStore
from maistro.memory.types import MemoryTier
from maistro.memory.working.manager import WorkingMemoryManager
from maistro.projects.store import InMemoryProjectStore

from ..working.test_working_memory import TopicEmbeddingClient, _mem


def _policy(
    store: InMemoryEpisodicStore,
    *,
    manager: WorkingMemoryManager | None = None,
    client: TopicEmbeddingClient | None = None,
) -> DefaultContextAssemblyPolicy:
    return DefaultContextAssemblyPolicy(
        episodic_store=store,
        outcome_store=InMemoryOutcomeStore(),
        project_store=InMemoryProjectStore(),
        embedding_client=client,
        working_memory=manager,
    )


def _manager(
    store: InMemoryEpisodicStore,
    *,
    workspace_id: str = "ws-1",
    client: TopicEmbeddingClient | None = None,
    **kwargs: Any,
) -> WorkingMemoryManager:
    return WorkingMemoryManager(
        workspace_id=workspace_id,
        episodic_store=store,
        embedding_client=client,
        **kwargs,
    )


class TestLayer1HotPath:
    async def test_query_recall_goes_through_the_hot_projection(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(_mem("PostgreSQL needs pgvector for similarity", memory_id="pg"))
        await store.store(_mem("Kafka partitions and brokers", memory_id="kf"))
        client = TopicEmbeddingClient()
        manager = _manager(store, client=client)
        policy = _policy(store, manager=manager, client=client)

        text = await policy.layer1(
            run_id="r1", agent_id="agent-1", session_id="s1", query="pgvector"
        )
        assert "pgvector" in text
        assert "Kafka partitions" not in text
        # Hot path: exactly one embed for the query; candidates were embedded
        # at hydrate time, not re-embedded per read.
        assert client.embed_calls == 3  # 2 at hydrate + 1 query
        assert manager.projection().stats.records == 2

    async def test_empty_query_keeps_store_listing_semantics(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(_mem("PostgreSQL needs pgvector", memory_id="pg"))
        client = TopicEmbeddingClient()
        manager = _manager(store, client=client)
        policy = _policy(store, manager=manager, client=client)
        text = await policy.layer1(run_id="r1", agent_id="agent-1", session_id="s1")
        assert "pgvector" in text

    async def test_scope_visibility_narrows_on_the_hot_path(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(_mem("PostgreSQL secrets for agent-1", memory_id="m1"))
        manager = _manager(store)
        policy = _policy(store, manager=manager)

        visible = await policy.layer1(
            run_id="r1", agent_id="agent-1", session_id="s1", query="PostgreSQL"
        )
        assert "agent-1" in visible

        hidden = await policy.layer1(
            run_id="r1", agent_id="agent-2", session_id="s1", query="PostgreSQL"
        )
        assert hidden == ""

    async def test_hydration_failure_degrades_to_durable_path_loudly(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import maistro.memory.working.manager as manager_module

        store = InMemoryEpisodicStore()
        await store.store(_mem("PostgreSQL needs pgvector", memory_id="pg"))
        manager = _manager(store)

        def explode(**_kwargs: Any) -> Any:
            raise RuntimeError("backend unavailable")

        monkeypatch.setattr(manager_module, "WorkspaceWorkingMemoryProjection", explode)
        policy = _policy(store, manager=manager)
        with caplog.at_level("ERROR"):
            text = await policy.layer1(
                run_id="r1", agent_id="agent-1", session_id="s1", query="pgvector"
            )
        # The durable path still answered, and the degradation is on record.
        assert "pgvector" in text
        assert "backend unavailable" in manager.degraded_reason()
        assert any(
            "working-memory backend init failed" in record.message for record in caplog.records
        )

    async def test_no_manager_behaves_exactly_as_before(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(_mem("PostgreSQL needs pgvector", memory_id="pg"))
        policy = _policy(store)
        text = await policy.layer1(
            run_id="r1", agent_id="agent-1", session_id="s1", query="pgvector"
        )
        assert "pgvector" in text

    async def test_mid_read_failure_heals_by_rebuild_for_the_next_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = InMemoryEpisodicStore()
        await store.store(_mem("PostgreSQL needs pgvector", memory_id="pg"))
        manager = _manager(store)
        policy = _policy(store, manager=manager)
        # Warm the projection so the failure below is a mid-read failure of a
        # constructed graph (the corruption signal), not a construction one.
        assert await manager.ensure_hydrated() is True
        healthy = manager.projection()

        original_recall = type(healthy).recall
        calls = {"count": 0}

        async def flaky_recall(self: Any, query: str, **kwargs: Any) -> Any:
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("torn index")
            return await original_recall(self, query, **kwargs)

        monkeypatch.setattr(type(healthy), "recall", flaky_recall)

        # The failing read is answered from the durable path...
        first = await policy.layer1(
            run_id="r1", agent_id="agent-1", session_id="s1", query="pgvector"
        )
        assert "pgvector" in first
        assert calls["count"] == 1
        # ...and ADR-082226-5104 §6's corruption answer ran: the projection
        # was discarded and rebuilt from authoritative truth, so the next
        # call is hot again with no recorded degradation and no durable write.
        assert manager.projection() is not healthy
        assert manager.degraded_reason() == ""
        second = await policy.layer1(
            run_id="r2", agent_id="agent-1", session_id="s1", query="pgvector"
        )
        assert "pgvector" in second
        assert calls["count"] == 2


class TestLayer4GraphContext:
    async def test_populated_workspace_gets_real_graph_context(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(_mem("PostgreSQL and LadybugDB split the memory tiers", memory_id="m1"))
        await store.store(_mem("PostgreSQL migration finished on time", memory_id="m2"))
        manager = _manager(store)
        policy = _policy(store, manager=manager)

        text = await policy.layer4(project_id="proj-1")
        assert text != ""
        assert "PostgreSQL" in text
        assert "LadybugDB" in text
        assert "associated with" in text  # the postgresql-ladybugdb edge
        assert "mentioned in" in text
        assert "[lesson w=0.70, run run-1]" in text  # canonical provenance rendered

    async def test_project_filter_narrows_citing_memories(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(_mem("PostgreSQL migration notes", memory_id="mine", project_id="proj-1"))
        await store.store(_mem("PostgreSQL rollback drill", memory_id="other", project_id="proj-2"))
        manager = _manager(store)
        policy = _policy(store, manager=manager)

        text = await policy.layer4(project_id="proj-1")
        assert "migration notes" in text
        assert "rollback drill" not in text

    async def test_empty_workspace_returns_empty_string(self) -> None:
        store = InMemoryEpisodicStore()
        manager = _manager(store)
        policy = _policy(store, manager=manager)
        assert await policy.layer4(project_id="proj-1") == ""

    async def test_no_manager_still_returns_empty_string(self) -> None:
        store = InMemoryEpisodicStore()
        policy = _policy(store)
        assert await policy.layer4(project_id="proj-1") == ""

    async def test_degraded_projection_returns_empty_not_fabrication(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import maistro.memory.working.manager as manager_module

        store = InMemoryEpisodicStore()
        await store.store(_mem("PostgreSQL and LadybugDB", memory_id="m1"))
        manager = _manager(store)

        def explode(**_kwargs: Any) -> Any:
            raise RuntimeError("backend unavailable")

        monkeypatch.setattr(manager_module, "WorkspaceWorkingMemoryProjection", explode)
        policy = _policy(store, manager=manager)
        assert await policy.layer4(project_id="proj-1") == ""
        assert manager.degraded_reason() != ""


class TestLayer4FailureAndRendering:
    async def test_long_memory_snippets_are_truncated_not_dumped(self) -> None:
        store = InMemoryEpisodicStore()
        filler = "x" * 400
        await store.store(_mem(f"PostgreSQL note with a long body {filler}", memory_id="m1"))
        policy = _policy(store, manager=_manager(store))

        text = await policy.layer4(project_id="proj-1")
        assert "mentioned in" in text
        # The snippet is capped so one memory cannot flood the layer...
        assert "..." in text
        # ...and the untruncated body never renders.
        assert filler not in text

    async def test_entity_context_failure_heals_for_the_next_call(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A mid-read entity-context failure is the layer4 corruption signal:
        serve none, log loudly, and run the ADR §6 discard-and-rebuild so the
        next call is hot again — with no durable write anywhere."""
        store = InMemoryEpisodicStore()
        await store.store(_mem("PostgreSQL and LadybugDB split the tiers", memory_id="m1"))
        manager = _manager(store)
        policy = _policy(store, manager=manager)
        assert await manager.ensure_hydrated() is True
        healthy = manager.projection()

        async def broken_entity_context(self: Any, *, project_id: str | None = None) -> Any:
            raise RuntimeError("torn entity index")

        monkeypatch.setattr(type(healthy), "entity_context", broken_entity_context)

        with caplog.at_level("ERROR"):
            assert await policy.layer4(project_id="proj-1") == ""
        assert any("layer4 graph context failed" in record.message for record in caplog.records)
        assert manager.projection() is not healthy
        assert manager.degraded_reason() == ""
        # The rebuild replaced the graph; the context is servable again once
        # the failure is lifted.
        monkeypatch.undo()
        assert await policy.layer4(project_id="proj-1") != ""

    async def test_rebuild_failure_is_logged_and_retries_are_throttled(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When even the corruption-heal rebuild fails, the policy must say so
        and keep answering from the durable path — and a deterministically
        failing read must not turn every retrieval into a re-index attempt."""
        store = InMemoryEpisodicStore()
        await store.store(_mem("PostgreSQL and LadybugDB split the tiers", memory_id="m1"))
        manager = _manager(store)
        policy = _policy(store, manager=manager)
        assert await manager.ensure_hydrated() is True
        healthy = manager.projection()

        async def broken_entity_context(self: Any, *, project_id: str | None = None) -> Any:
            raise RuntimeError("torn entity index")

        monkeypatch.setattr(type(healthy), "entity_context", broken_entity_context)
        rebuild_calls = {"count": 0}

        async def failing_rebuild(self: Any, **_kwargs: Any) -> bool:
            rebuild_calls["count"] += 1
            raise RuntimeError("backend down during rebuild")

        monkeypatch.setattr(WorkingMemoryManager, "rebuild", failing_rebuild)

        with caplog.at_level("ERROR"):
            first = await policy.layer4(project_id="proj-1")
            second = await policy.layer4(project_id="proj-1")
        # Both reads are honestly empty — never a fabricated graph context.
        assert first == ""
        assert second == ""
        # The rebuild ran once (throttled), its failure is on the record...
        assert rebuild_calls == {"count": 1}
        assert any("corruption-heal rebuild failed" in record.message for record in caplog.records)
        # ...and the graph itself was never discarded by a rebuild that could
        # not complete.
        assert manager.projection() is healthy


class TestAssembleIntegration:
    async def test_assemble_includes_layer4_when_wired(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(_mem("PostgreSQL and LadybugDB split the tiers", memory_id="m1"))
        manager = _manager(store)
        policy = _policy(store, manager=manager)

        text = await policy.assemble(
            project_id="proj-1",
            run_id="r1",
            agent_id="agent-1",
            session_id="s1",
            budget_tokens=4000,
            query="PostgreSQL",
            org_id="org-1",
        )
        assert "PostgreSQL" in text
        assert "associated with" in text

    async def test_hypothesis_tier_reaches_layer1_hot_recall(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(
            _mem(
                "PostgreSQL sharding hypothesis needs measurement",
                memory_id="hyp",
                tier=MemoryTier.HYPOTHESIS,
                weight=0.5,
            )
        )
        manager = _manager(store)
        policy = _policy(store, manager=manager)
        text = await policy.layer1(
            run_id="r1", agent_id="agent-1", session_id="s1", query="sharding hypothesis"
        )
        assert "sharding hypothesis" in text


class TestNoSilentPretense:
    async def test_projection_with_no_embeddings_never_claims_vector_ready(self) -> None:
        store = InMemoryEpisodicStore()
        manager = _manager(store)  # no embedding client
        policy = _policy(store, manager=manager)
        await policy.layer1(run_id="r1", agent_id="agent-1", session_id="s1", query="anything")
        stats = manager.projection().stats
        assert stats.vector_ready is False
        assert stats.degraded_reason != ""
        # Lexical recall still served the layer honestly.
        assert stats.records == 0
