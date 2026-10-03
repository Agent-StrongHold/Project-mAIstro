"""Working-memory projection conformance (ADR-082226-5104 §5-6, issue #301).

The properties each test pins, in acceptance-criterion order:

* a Workspace lazily hydrates a working graph from authoritative memory;
* two Workspaces cannot observe or traverse each other's graph even with
  identical entity names and memory ids;
* the projection can be discarded and rebuilt with no durable change;
* lexical recall is BM25 over an inverted index (idf-weighted, postings-driven);
* semantic recall reads embeddings stored at write time (one embed per read,
  for the query alone);
* a content update re-indexes and re-embeds — the previous content's index
  entries and vector are gone;
* failures are observable: a failing embedding leaves the record lexical-only
  with a degraded_reason, never a stale vector; a failing hydration read is
  logged, recorded, and answered with False, never silently skipped;
* hydrate -> retrieve/traverse -> evict -> rehydrate and restart/rebuild.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any

import pytest

from maistro.memory.types import EpisodicMemory, MemoryScope, MemoryTier
from maistro.memory.working.dreaming import collect_candidates
from maistro.memory.working.extraction import GovernedEntityExtractor
from maistro.memory.working.manager import WorkingMemoryError, WorkingMemoryManager
from maistro.memory.working.projection import WorkspaceWorkingMemoryProjection
from maistro.memory.working.protocol import WorkingMemory


class TopicEmbeddingClient:
    """Deterministic topic embeddings: one dimension per known topic word.

    Real enough to make similarity meaningful (a "postgres" query is close to
    a "postgres" memory and far from a "kafka" one), deterministic enough to
    assert on, and instrumented so tests can prove exactly when embedding
    happens.
    """

    _TOPICS = ("postgres", "kafka", "ladybug", "vector")

    def __init__(self, dim: int = 8, fail_after: int | None = None) -> None:
        self.dim = dim
        self.embed_calls = 0
        self._fail_after = fail_after

    @property
    def dimension(self) -> int:
        return self.dim

    def vector_for(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        lowered = text.lower()
        for index, topic in enumerate(self._TOPICS):
            if topic in lowered:
                vec[index] = 1.0
        return vec

    async def embed(self, text: str) -> list[float]:
        self.embed_calls += 1
        if self._fail_after is not None and self.embed_calls > self._fail_after:
            raise RuntimeError("embedding backend unavailable")
        return self.vector_for(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(text) for text in texts]


def _mem(
    content: str,
    *,
    memory_id: str = "",
    tier: MemoryTier = MemoryTier.LESSON,
    weight: float = 0.7,
    agent_id: str | None = "agent-1",
    org_id: str = "org-1",
    project_id: str = "proj-1",
    run_id: str = "run-1",
    node_run_id: str = "node-1",
    attempt_id: str = "attempt-1",
    context: dict[str, Any] | None = None,
    scope: MemoryScope = MemoryScope.AGENT,
    deleted: bool = False,
) -> EpisodicMemory:
    return EpisodicMemory(
        memory_id=memory_id or hashlib.md5(content.encode()).hexdigest(),
        tier=tier,
        content=content,
        weight=weight,
        org_id=org_id,
        agent_id=agent_id,
        project_id=project_id,
        run_id=run_id,
        node_run_id=node_run_id,
        attempt_id=attempt_id,
        context=context or {},
        scope=scope,
        deleted=deleted,
    )


def _projection(
    workspace_id: str = "ws-a",
    client: TopicEmbeddingClient | None = None,
    **kwargs: Any,
) -> WorkspaceWorkingMemoryProjection:
    return WorkspaceWorkingMemoryProjection(
        workspace_id=workspace_id,
        embedding_client=client,
        embedding_model=kwargs.pop("embedding_model", "stub-embedder-v1"),
        **kwargs,
    )


class TestProtocolConformance:
    async def test_projection_satisfies_working_memory_protocol(self) -> None:
        assert isinstance(_projection(), WorkingMemory)


class TestHydration:
    async def test_hydrate_counts_and_second_pass_is_all_unchanged(self) -> None:
        projection = _projection()
        report = await projection.hydrate(
            [
                _mem("postgres needs pgvector", memory_id="m1"),
                _mem("kafka partitions", memory_id="m2"),
            ]
        )
        assert (report.hydrated, report.updated, report.unchanged) == (2, 0, 0)
        assert projection.stats.records == 2

        again = await projection.hydrate(
            [
                _mem("postgres needs pgvector", memory_id="m1"),
                _mem("kafka partitions", memory_id="m2"),
            ]
        )
        assert (again.hydrated, again.updated, again.unchanged) == (0, 0, 2)
        assert projection.stats.records == 2

    async def test_weight_change_updates_and_content_change_reindexes(self) -> None:
        projection = _projection()
        await projection.hydrate([_mem("postgres needs pgvector", memory_id="m1", weight=0.5)])
        moved = await projection.hydrate(
            [_mem("postgres needs pgvector", memory_id="m1", weight=0.8)]
        )
        assert moved.updated == 1
        recalled = await projection.recall_lexical("postgres")
        assert recalled[0].memory.weight == 0.8

        rewritten = await projection.hydrate([_mem("kafka partitions", memory_id="m1")])
        assert rewritten.updated == 1
        assert await projection.recall_lexical("postgres") == []
        assert [h.memory.memory_id for h in await projection.recall_lexical("kafka")] == ["m1"]

    async def test_deleted_durable_record_leaves_projection_on_rehydrate(self) -> None:
        projection = _projection()
        await projection.hydrate([_mem("postgres needs pgvector", memory_id="m1")])
        report = await projection.hydrate(
            [_mem("postgres needs pgvector", memory_id="m1", deleted=True)]
        )
        assert report.deleted == 1
        assert projection.stats.records == 0

    async def test_hydration_preserves_canonical_provenance(self) -> None:
        projection = _projection()
        await projection.hydrate([_mem("postgres needs pgvector", memory_id="m1")])
        hits = await projection.recall_lexical("postgres")
        memory = hits[0].memory
        assert (memory.run_id, memory.node_run_id, memory.attempt_id) == (
            "run-1",
            "node-1",
            "attempt-1",
        )
        assert memory.project_id == "proj-1"
        assert memory.memory_id == "m1"


class TestSnapshotReconciliation:
    """The manager's by-ID reconciliation of the snapshot hydration path.

    Every ``list_by_scope`` implementation filters deleted records, so the
    snapshot ``ensure_hydrated()`` fetches cannot carry the tombstones
    ``hydrate`` consumes; records that left the durable store after hydration
    must be reconciled away by ID, and the explicit-``memories`` path must
    neither read the store nor reconcile (its caller owns the record set).
    """

    async def test_explicit_memories_skip_the_durable_read_and_reconciliation(self) -> None:
        from maistro.memory.episodic.store import InMemoryEpisodicStore

        class CountingStore(InMemoryEpisodicStore):
            reads = 0

            async def list_by_scope(self, **kwargs: Any) -> list[EpisodicMemory]:
                CountingStore.reads += 1
                return await super().list_by_scope(**kwargs)

        store = CountingStore()
        manager = WorkingMemoryManager(workspace_id="ws-a", episodic_store=store)

        assert (
            await manager.ensure_hydrated(
                memories=[_mem("postgres needs pgvector", memory_id="m1")]
            )
            is True
        )
        assert CountingStore.reads == 0
        hits = await manager.projection().recall_lexical("postgres")
        assert [h.memory.memory_id for h in hits] == ["m1"]

    async def test_snapshot_reconciliation_drops_records_missing_from_durable(self) -> None:
        from maistro.memory.episodic.store import InMemoryEpisodicStore

        store = InMemoryEpisodicStore()
        await store.store(_mem("postgres needs pgvector", memory_id="m1"))
        manager = WorkingMemoryManager(workspace_id="ws-a", episodic_store=store)
        # A record that was hydrated earlier but has since left the durable
        # store (deleted, or absorbed by a consolidation): the durable snapshot
        # no longer returns it.
        assert (
            await manager.ensure_hydrated(
                memories=[
                    _mem("postgres needs pgvector", memory_id="m1"),
                    _mem("absorbed consolidation note", memory_id="m2"),
                ]
            )
            is True
        )
        assert await manager.projection().recall_lexical("absorbed") != []

        # Snapshot hydrate: m2 is absent from the read, so reconciliation
        # drops it; m1 is unchanged and stays searchable.
        assert await manager.ensure_hydrated() is True
        assert await manager.projection().recall_lexical("absorbed") == []
        hits = await manager.projection().recall_lexical("postgres")
        assert [h.memory.memory_id for h in hits] == ["m1"]


class TestIndexedRecall:
    async def test_bm25_ranks_rare_term_above_common_term(self) -> None:
        projection = _projection()
        records = [
            _mem("the team ships every week", memory_id="common"),
            _mem("postgres needs pgvector for similarity", memory_id="rare"),
            _mem("weekly notes about the team and the plan", memory_id="filler"),
        ]
        await projection.hydrate(records)
        hits = await projection.recall_lexical("postgres pgvector similarity")
        assert [hit.memory.memory_id for hit in hits] == ["rare"]
        assert hits[0].lexical_score > 0.0

    async def test_index_is_a_real_inverted_index(self) -> None:
        projection = _projection()
        await projection.hydrate([_mem("postgres needs pgvector", memory_id="m1")])
        stats = projection.stats
        assert stats.index_terms >= 3
        assert "postgres" in projection._postings
        assert projection._postings["postgres"] == {"m1": 1}

    async def test_vector_recall_embeds_the_query_once_never_the_candidates(self) -> None:
        client = TopicEmbeddingClient()
        projection = _projection(client=client)
        await projection.hydrate(
            [
                _mem("postgres needs pgvector for similarity", memory_id="pg"),
                _mem("kafka partitions and brokers", memory_id="kf"),
                _mem("ladybug holds the hot graph", memory_id="lb"),
            ]
        )
        hydrated_calls = client.embed_calls
        assert hydrated_calls == 3  # stored at write time

        hits = await projection.recall("postgres pgvector")
        assert client.embed_calls == hydrated_calls + 1  # the query alone
        assert hits[0].memory.memory_id == "pg"
        assert hits[0].vector_score > 0.0

    async def test_recall_vector_accepts_caller_supplied_embedding(self) -> None:
        client = TopicEmbeddingClient()
        projection = _projection(client=client)
        await projection.hydrate([_mem("kafka partitions and brokers", memory_id="kf")])
        hits = await projection.recall_vector(client.vector_for("kafka"))
        assert [hit.memory.memory_id for hit in hits] == ["kf"]
        assert client.embed_calls == 1  # hydrate only; no query embed

    async def test_lexical_recall_needs_no_embedding_client(self) -> None:
        projection = _projection(client=None)
        await projection.hydrate([_mem("postgres needs pgvector", memory_id="pg")])
        assert projection.stats.vector_ready is False
        assert projection.stats.degraded_reason != ""
        hits = await projection.recall_lexical("postgres")
        assert [hit.memory.memory_id for hit in hits] == ["pg"]


class TestScopePreservation:
    async def test_agent_scoped_memory_invisible_to_another_agent(self) -> None:
        projection = _projection()
        await projection.hydrate([_mem("postgres secrets", memory_id="m1")])
        assert await projection.recall("postgres", agent_id="agent-2") == []
        hits = await projection.recall("postgres", agent_id="agent-1")
        assert [hit.memory.memory_id for hit in hits] == ["m1"]

    async def test_org_scoped_memory_hidden_from_other_orgs(self) -> None:
        projection = _projection()
        await projection.hydrate(
            [
                _mem(
                    "postgres secrets",
                    memory_id="m1",
                    agent_id=None,
                    org_id="org-1",
                    scope=MemoryScope.ORGANIZATION,
                )
            ]
        )
        # Mirrors `EpisodicStore.list_by_scope`: no scope axis named means
        # project-style selection, not an implicit wildcard denial.
        assert len(await projection.recall("postgres")) == 1
        assert len(await projection.recall("postgres", org_id="org-1")) == 1
        assert await projection.recall("postgres", org_id="org-2") == []

    async def test_min_weight_and_project_filters_apply(self) -> None:
        projection = _projection()
        await projection.hydrate(
            [
                _mem("postgres lessons", memory_id="low", weight=0.2),
                _mem("postgres elsewhere", memory_id="other-project", project_id="proj-2"),
                _mem("postgres here", memory_id="kept"),
            ]
        )
        ids = {hit.memory.memory_id for hit in await projection.recall("postgres", min_weight=0.3)}
        assert ids == {"other-project", "kept"}
        ids = {
            hit.memory.memory_id for hit in await projection.recall("postgres", project_id="proj-1")
        }
        assert ids == {"kept", "low"}  # project filter, no weight floor


class TestUpdateConsistency:
    async def test_content_update_reindexes_and_reembeds(self) -> None:
        client = TopicEmbeddingClient()
        projection = _projection(client=client)
        await projection.store(_mem("postgres needs pgvector", memory_id="m1"))

        await projection.update("m1", content="kafka partitions and brokers")
        assert await projection.recall_lexical("postgres") == []
        hits = await projection.recall_lexical("kafka")
        assert [hit.memory.memory_id for hit in hits] == ["m1"]
        # The stored vector now describes the new content: a kafka query
        # vector finds it, a postgres one does not.
        found = await projection.recall_vector(client.vector_for("kafka"))
        assert [hit.memory.memory_id for hit in found] == ["m1"]
        assert await projection.recall_vector(client.vector_for("postgres")) == []

    async def test_weight_only_update_keeps_embedding(self) -> None:
        client = TopicEmbeddingClient()
        projection = _projection(client=client)
        await projection.store(_mem("postgres needs pgvector", memory_id="m1"))
        before = client.embed_calls
        await projection.update("m1", weight=0.9)
        assert client.embed_calls == before  # content unchanged: no re-embed
        hits = await projection.recall_lexical("postgres")
        assert hits[0].memory.weight == 0.9

    async def test_failed_reembed_leaves_record_lexical_only_never_stale(self) -> None:
        client = TopicEmbeddingClient(fail_after=1)
        projection = _projection(client=client)
        await projection.store(_mem("postgres needs pgvector", memory_id="m1"))
        # The write-path embed failure degrades explicitly (the codebase's
        # established semantics: a failed embedding never fails the write,
        # but the record must not pretend to be vector-served).
        await projection.update("m1", content="kafka partitions")
        stats = projection.stats
        assert stats.embedding_failures == 1
        assert stats.vector_ready is False
        assert "lexical-only" in stats.degraded_reason
        # Lexically the new content is served; the old vector is gone.
        assert await projection.recall_lexical("kafka")

    async def test_model_identity_change_drops_stale_vectors(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        client = TopicEmbeddingClient()
        projection = _projection(client=client, embedding_model="embedder-v1")
        await projection.store(_mem("postgres needs pgvector", memory_id="m1"))
        assert projection.stats.embedded_records == 1

        projection._embedding_model = "embedder-v2"
        with caplog.at_level("WARNING"):
            await projection.store(_mem("kafka partitions", memory_id="m2"))
        stats = projection.stats
        # The v1 vector was dropped (logged), not mixed with the v2 one.
        assert any(
            "dropping 1 vectors from model 'embedder-v1'" in r.message for r in caplog.records
        )
        assert stats.embedded_records == 1  # only the v2 record carries a vector
        found = await projection.recall_vector(client.vector_for("kafka"))
        assert [hit.memory.memory_id for hit in found] == ["m2"]
        assert await projection.recall_vector(client.vector_for("postgres")) == []


class TestEntityGraph:
    async def test_lexical_extraction_builds_mentioned_in_edges(self) -> None:
        projection = _projection()
        await projection.hydrate(
            [_mem("PostgreSQL and LadybugDB split durable from working memory", memory_id="m1")]
        )
        postgres = await projection.lookup_entity("postgresql")
        assert postgres is not None
        assert postgres.mention_count == 1
        assert postgres.memory_ids == ("m1",)
        ladybug = await projection.lookup_entity("ladybugdb")
        assert ladybug is not None and ladybug.memory_ids == ("m1",)

    async def test_declared_entities_win_over_extraction(self) -> None:
        projection = _projection()
        await projection.hydrate(
            [_mem("the migration plan", memory_id="m1", context={"entities": ["acme Corp"]})]
        )
        assert await projection.lookup_entity("acme corp") is not None

    async def test_cooccurrence_edges_count_observations(self) -> None:
        projection = _projection()
        await projection.hydrate(
            [
                _mem("Ada met Bob", memory_id="m1"),
                _mem("Bob and Ada again", memory_id="m2"),
            ]
        )
        relations = await projection.relations_for("ada")
        assert [(r.source, r.target) for r in relations] == [("ada", "bob")]
        assert relations[0].weight == 2.0

    async def test_delete_prunes_mentions_and_edges(self) -> None:
        projection = _projection()
        await projection.hydrate(
            [_mem("Ada met Bob", memory_id="m1"), _mem("Bob met Carol", memory_id="m2")]
        )
        await projection.delete("m1")
        assert await projection.lookup_entity("ada") is None
        bob = await projection.lookup_entity("bob")
        assert bob is not None and bob.memory_ids == ("m2",)
        # The ada-bob edge died with ada; bob-carol survives.
        assert [(r.source, r.target, r.weight) for r in await projection.relations_for("bob")] == [
            ("bob", "carol", 1.0)
        ]

    async def test_traverse_is_bounded_and_stays_inside_the_graph(self) -> None:
        projection = _projection()
        await projection.hydrate(
            [
                _mem("Ada paired with Bob", memory_id="m1"),
                _mem("Bob paired with Carol", memory_id="m2"),
                _mem("Carol paired with Dave", memory_id="m3"),
            ]
        )
        one_hop = await projection.traverse("ada", max_depth=1)
        assert set(one_hop.visited) == {"ada", "bob"}
        two_hop = await projection.traverse("ada", max_depth=2)
        assert set(two_hop.visited) == {"ada", "bob", "carol"}
        missing = await projection.traverse("nonexistent")
        assert missing.visited == ()

    async def test_governed_extractor_is_used_and_failures_are_visible(self) -> None:
        seen: list[str] = []

        async def governed(text: str) -> list[str]:
            seen.append(text)
            return ["Governed Entity"]

        projection = _projection(entity_extractor=GovernedEntityExtractor(governed))
        await projection.hydrate([_mem("some content", memory_id="m1")])
        assert seen == ["some content"]
        assert await projection.lookup_entity("governed entity") is not None

        async def broken(_text: str) -> list[str]:
            raise RuntimeError("governed model path failed")

        failing = _projection(entity_extractor=GovernedEntityExtractor(broken))
        with pytest.raises(RuntimeError, match="governed model path"):
            await failing.hydrate([_mem("some content", memory_id="m2")])

    async def test_project_layer4_skips_entities_with_no_citing_memories(self) -> None:
        projection = _projection()
        memories: list[EpisodicMemory] = []
        for index in range(8):
            entity = f"Foreign Entity {index}"
            for dup in range(3):
                memories.append(
                    _mem(
                        f"{entity} operational note {index}-{dup}",
                        memory_id=f"f-{index}-{dup}",
                        project_id="proj-other",
                        context={"entities": [entity]},
                    )
                )
        memories.append(
            _mem(
                "Zephyr Tool ships the tiny feature",
                memory_id="p-1",
                project_id="proj-1",
                context={"entities": ["Zephyr Tool"]},
            )
        )
        await projection.hydrate(memories)

        # The eight foreign entities out-rank "zephyr tool" on raw mentions;
        # Layer 4 for proj-1 must rank only entities citing proj-1 memories,
        # so the limit cannot crowd the project's own entity out.
        contexts = await projection.entity_context(project_id="proj-1")
        assert [e.entity.name for e in contexts] == ["zephyr tool"]
        assert contexts[0].memories and all(
            m.project_id == "proj-1" for e in contexts for m in e.memories
        )

        # Workspace-wide view (no project) keeps the plain mention-ranked
        # top 8 — the foreign entities out-mention "zephyr tool" there.
        unscoped = await projection.entity_context()
        assert len(unscoped) == 8
        assert all(e.entity.name.startswith("foreign entity") for e in unscoped)


class TestWorkspaceIsolation:
    async def test_identical_ids_and_entities_do_not_cross_workspaces(self) -> None:
        ws_a = _projection(workspace_id="ws-a")
        ws_b = _projection(workspace_id="ws-b")
        # The *same* memory id and the same entity names, in both Workspaces —
        # the hostile case for any shared index.
        record_a = _mem("PostgreSQL migration notes for team Rocket", memory_id="shared-id")
        record_b = _mem("PostgreSQL rollback plan for team Rocket", memory_id="shared-id")
        await ws_a.hydrate([record_a])
        await ws_b.hydrate([record_b])

        a_hits = await ws_a.recall_lexical("rollback")
        assert a_hits == []
        b_hits = await ws_b.recall_lexical("rollback")
        assert [h.memory.memory_id for h in b_hits] == ["shared-id"]

        # Same entity name in both Workspaces, but each graph cites only its
        # own Workspace's memory content.
        a_content = ws_a.records()[0].content
        b_content = ws_b.records()[0].content
        assert a_content != b_content
        a_entity = await ws_a.lookup_entity("postgresql")
        assert a_entity is not None and a_entity.memory_ids == ("shared-id",)
        b_entity = await ws_b.lookup_entity("postgresql")
        assert b_entity is not None and b_entity.memory_ids == ("shared-id",)
        b_context = await ws_b.entity_context()
        assert {m.content for e in b_context for m in e.memories} == {b_content}

    async def test_traversal_cannot_reach_another_workspace_entity(self) -> None:
        ws_a = _projection(workspace_id="ws-a")
        ws_b = _projection(workspace_id="ws-b")
        await ws_a.hydrate([_mem("Ada paired with Bob", memory_id="m1")])
        await ws_b.hydrate([_mem("Bob paired with Carol", memory_id="m2")])
        result = await ws_a.traverse("bob", max_depth=3)
        assert "carol" not in result.visited
        assert set(result.visited) == {"bob", "ada"}

    async def test_manager_hands_out_distinct_projections(self) -> None:
        manager = self._manager()
        a = manager.projection("ws-a")
        b = manager.projection("ws-b")
        assert a is not b
        assert a.workspace_id == "ws-a" and b.workspace_id == "ws-b"
        assert manager.projection("ws-a") is a

    def _manager(self, **kwargs: Any) -> WorkingMemoryManager:
        from maistro.memory.episodic.store import InMemoryEpisodicStore

        return WorkingMemoryManager(
            workspace_id="ws-a",
            episodic_store=InMemoryEpisodicStore(),
            **kwargs,
        )


class TestEvictionAndRebuild:
    async def test_hydrate_retrieve_evict_rehydrate(self) -> None:
        from maistro.memory.episodic.store import InMemoryEpisodicStore

        store = InMemoryEpisodicStore()
        durable_before = await store.list_by_scope(limit=100)
        manager = WorkingMemoryManager(workspace_id="ws-a", episodic_store=store)
        await store.store(_mem("postgres needs pgvector", memory_id="m1"))

        assert await manager.ensure_hydrated() is True
        hits = await manager.projection().recall_lexical("postgres")
        assert [h.memory.memory_id for h in hits] == ["m1"]

        assert manager.evict() is True
        assert manager.active_workspace_ids == []
        # Durable state untouched by eviction.
        durable_after = await store.list_by_scope(limit=100)
        assert len(durable_after) == len(durable_before) + 1

        # Rehydrate: same answers from a fresh projection.
        assert await manager.ensure_hydrated() is True
        hits = await manager.projection().recall_lexical("postgres")
        assert [h.memory.memory_id for h in hits] == ["m1"]
        report = await manager.projection().hydrate(await store.list_by_scope(limit=100))
        assert report.unchanged == 1  # idempotent across rebuild

    async def test_reset_discards_content_and_counts_a_rebuild(self) -> None:
        projection = _projection()
        await projection.hydrate([_mem("postgres needs pgvector", memory_id="m1")])
        await projection.reset()
        stats = projection.stats
        assert stats.records == 0
        assert stats.rebuilds == 1
        assert await projection.recall_lexical("postgres") == []

    async def test_idle_ttl_sweep_evicts_only_stale_projections(self) -> None:
        from maistro.memory.episodic.store import InMemoryEpisodicStore

        class FakeClock:
            now = 1000.0

            @staticmethod
            def monotonic() -> float:
                return FakeClock.now

        manager = WorkingMemoryManager(
            workspace_id="ws-a",
            episodic_store=InMemoryEpisodicStore(),
            idle_ttl_seconds=100.0,
            clock=FakeClock,
        )
        manager.projection("ws-hot")
        FakeClock.now = 1050.0
        manager.projection("ws-cold")
        FakeClock.now = 1150.0
        manager.projection("ws-hot")  # recent use keeps it hot
        FakeClock.now = 1200.0
        evicted = manager.evict_idle()
        assert evicted == ["ws-cold"]
        assert manager.active_workspace_ids == ["ws-hot"]
        assert manager.evictions == 1

    async def test_access_sweeps_idle_projections_and_counts_them(self) -> None:
        from maistro.memory.episodic.store import InMemoryEpisodicStore

        class FakeClock:
            now = 1000.0

            @staticmethod
            def monotonic() -> float:
                return FakeClock.now

        manager = WorkingMemoryManager(
            workspace_id="ws-a",
            episodic_store=InMemoryEpisodicStore(),
            idle_ttl_seconds=100.0,
            clock=FakeClock,
        )
        manager.projection("ws-hot")
        FakeClock.now = 1200.0

        # Serving one Workspace is the amortized sweep point: the graph being
        # served never evicts itself, but the Workspace idle past the TTL is
        # dropped on the way in, with the lifetime counters to show for it.
        manager.projection("ws-a")
        assert manager.active_workspace_ids == ["ws-a"]
        assert manager.evictions == 1
        # The evicted Workspace lazily rehydrates on next use; durable state
        # is untouched by any of this.
        assert manager.projection("ws-hot") is not None
        assert manager.evictions == 1


class TestFailureObservability:
    async def test_hydration_read_failure_is_recorded_not_swallowed(self) -> None:
        from maistro.memory.episodic.store import InMemoryEpisodicStore

        class FailingStore(InMemoryEpisodicStore):
            async def list_by_scope(self, **kwargs: Any) -> list[EpisodicMemory]:
                raise RuntimeError("durable store unreachable")

        manager = WorkingMemoryManager(workspace_id="ws-a", episodic_store=FailingStore())
        assert await manager.ensure_hydrated() is False
        assert "durable store unreachable" in manager.degraded_reason()

    async def test_backend_init_failure_raises_and_degrades(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import maistro.memory.working.manager as manager_module
        from maistro.memory.episodic.store import InMemoryEpisodicStore

        manager = WorkingMemoryManager(workspace_id="ws-a", episodic_store=InMemoryEpisodicStore())

        def explode(**_kwargs: Any) -> WorkspaceWorkingMemoryProjection:
            raise RuntimeError("ladybug cannot open database")

        monkeypatch.setattr(manager_module, "WorkspaceWorkingMemoryProjection", explode)
        with pytest.raises(WorkingMemoryError, match="ladybug cannot open"):
            manager.projection()
        assert "ladybug cannot open" in manager.degraded_reason()
        assert await manager.ensure_hydrated() is False

    async def test_rebuild_recovers_after_recorded_degradation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import maistro.memory.working.manager as manager_module
        from maistro.memory.episodic.store import InMemoryEpisodicStore

        store = InMemoryEpisodicStore()
        await store.store(_mem("postgres needs pgvector", memory_id="m1"))
        manager = WorkingMemoryManager(workspace_id="ws-a", episodic_store=store)

        real = manager_module.WorkspaceWorkingMemoryProjection
        monkeypatch.setattr(
            manager_module,
            "WorkspaceWorkingMemoryProjection",
            lambda **kwargs: (_ for _ in ()).throw(RuntimeError("transient backend failure")),
        )
        assert await manager.rebuild() is False
        monkeypatch.setattr(manager_module, "WorkspaceWorkingMemoryProjection", real)

        assert await manager.rebuild() is True
        assert manager.degraded_reason() == ""
        hits = await manager.projection().recall_lexical("postgres")
        assert [h.memory.memory_id for h in hits] == ["m1"]


class TestDreamingCandidates:
    async def test_candidate_set_is_read_only_and_complete(self) -> None:
        from maistro.memory.episodic.store import InMemoryEpisodicStore

        projection = _projection()
        hypothesis = _mem(
            "PostgreSQL might shard by tenant",
            memory_id="hyp-1",
            tier=MemoryTier.HYPOTHESIS,
            weight=0.4,
        )
        lesson = _mem("PostgreSQL needs pgvector for similarity", memory_id="les-1")
        await projection.hydrate([hypothesis, lesson])

        store = InMemoryEpisodicStore()
        durable_snapshot = replace(lesson)

        candidates = await collect_candidates(projection)
        assert candidates.workspace_id == "ws-a"
        assert {m.memory_id for m in candidates.memories} == {"hyp-1", "les-1"}
        assert [m.memory_id for m in candidates.hypotheses] == ["hyp-1"]
        assert [e.name for e in candidates.entities] == ["postgresql"]
        assert [(r.source, r.target, r.weight) for r in candidates.relations] == []
        # A single entity is its own (singleton) co-occurrence cluster.
        assert candidates.clusters == (("postgresql",),)

        # Reading candidates wrote nothing anywhere.
        assert await store.list_by_scope(limit=10) == []
        assert projection.stats.records == 2
        assert projection._records["les-1"] == durable_snapshot

    async def test_candidate_set_groups_disjoint_entity_neighbourhoods(self) -> None:
        projection = _projection()
        await projection.hydrate(
            [
                _mem(
                    "PostgreSQL needs pgvector",
                    memory_id="m1",
                    context={"entities": ["PostgreSQL", "pgvector"]},
                ),
                _mem(
                    "Kafka partitions and brokers",
                    memory_id="m2",
                    context={"entities": ["Kafka", "brokers"]},
                ),
            ]
        )

        candidates = await collect_candidates(projection)
        # Two memories that share no entity form two connected clusters, each
        # discovered by bounded traversal from an unvisited entity.
        assert sorted(frozenset(cluster) for cluster in candidates.clusters) == [
            frozenset({"brokers", "kafka"}),
            frozenset({"pgvector", "postgresql"}),
        ]
