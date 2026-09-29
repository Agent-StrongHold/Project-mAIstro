"""Hydration and provenance: durable truth becomes graph-backed context (#776).

Covers the M3 acceptance properties that make the projection usable: lazy
hydration from real durable stores, canonical references surviving into
retrieved context, and durably recorded corrections / artifact versions
becoming available after hydration or an incremental refresh.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from maistro.memory.episodic.store import InMemoryEpisodicStore
from maistro.memory.working_graph import (
    ArtifactHistorySource,
    ArtifactVersionRecord,
    DurableMemorySource,
    RunProvenanceHydrationSource,
    RunProvenanceRecord,
    ScopeSelection,
    TerminologyHydrationSource,
    WorkspaceWorkingMemoryManager,
)
from maistro.memory.working_graph.backend import EmbeddedGraphBackend
from maistro.memory.working_graph.hydration import (
    TerminologyRecord,
    WorkingMemorySnapshot,
)
from maistro.memory.working_graph.types import (
    CanonicalRef,
    EdgeRelation,
    NodeKind,
    WorkingGraphNode,
    WorkingMemoryHealth,
    node_id_for,
)

from .conftest import (
    WORKSPACE_A,
    FakeArtifactSource,
    FakeRunProvenanceSource,
    FakeTerminologySource,
    make_learning,
    make_memory,
)

SCOPE = ScopeSelection(org_id="org-1", team_id="team-1", user_id="user-1")


class BoundedDurableSource(DurableMemorySource):
    """Wraps the durable source and re-caps the hydration limit it is given."""

    async def collect(self, workspace_id: str, *, limit: int) -> WorkingMemorySnapshot:
        assert limit > 0
        return await super().collect(workspace_id, limit=min(limit, 3))


async def test_lazy_hydration_happens_on_first_use(
    episodic: InMemoryEpisodicStore,
) -> None:
    await episodic.store(make_memory("mem-1", "The brand palette is slate and amber"))
    manager = WorkspaceWorkingMemoryManager(
        sources=[DurableMemorySource(episodic=episodic, scope=SCOPE)]
    )

    # Not yet hydrated: asking for status does not create a graph for a
    # Workspace that has not asked for context.
    assert await manager.status(WORKSPACE_A) is None

    context = await manager.context(WORKSPACE_A, "brand palette")
    assert context.health is WorkingMemoryHealth.HEALTHY
    assert [node.ref.memory_id for node in context.nodes] == ["mem-1"]

    status = await manager.status(WORKSPACE_A)
    assert status is not None
    assert status.hydrated is True
    assert status.node_count == 1


async def test_retrieved_context_retains_canonical_references(
    episodic: InMemoryEpisodicStore,
) -> None:
    await episodic.store(
        make_memory(
            "mem-7",
            "Render hero shots at 4k for print work",
            run_id="run-9",
            node_run_id="nrun-3",
            attempt_id="att-2",
            project_id="proj-1",
        )
    )
    manager = WorkspaceWorkingMemoryManager(
        sources=[DurableMemorySource(episodic=episodic, scope=SCOPE)]
    )
    context = await manager.context(WORKSPACE_A, "hero shots")

    node = context.nodes[0]
    assert node.kind is NodeKind.MEMORY
    assert node.node_id == node_id_for(NodeKind.MEMORY, "mem-7")
    assert node.ref.workspace_id == WORKSPACE_A
    assert node.ref.memory_id == "mem-7"
    assert node.ref.run_id == "run-9"
    assert node.ref.node_run_id == "nrun-3"
    assert node.ref.attempt_id == "att-2"
    assert node.ref.project_id == "proj-1"
    # The rendered block keeps the references, so a consumer quoting the
    # context is quoting durable identities, not graph-local guesses.
    text = context.to_text()
    assert "memory_id=mem-7" in text
    assert "run_id=run-9" in text


async def test_correction_recorded_durably_becomes_available_after_refresh(
    episodic: InMemoryEpisodicStore,
    learnings,
) -> None:
    await episodic.store(make_memory("mem-1", "Layout uses a 12 column grid"))
    manager = WorkspaceWorkingMemoryManager(
        sources=[DurableMemorySource(episodic=episodic, learnings=learnings, scope=SCOPE)]
    )
    first = await manager.context(WORKSPACE_A, "grid")
    assert first.nodes and first.health is WorkingMemoryHealth.HEALTHY

    # The user corrects the record; it becomes durable truth in the learning
    # store. The projection is a snapshot, so it must not silently invent the
    # correction — only the refresh admits it.
    await learnings.store(
        make_learning("Never use 16 columns; the user corrected this", run_id="run-77")
    )
    stale = await manager.context(WORKSPACE_A, "columns")
    assert all(node.kind is not NodeKind.LEARNING for node in stale.nodes)

    graph = await manager.graph(WORKSPACE_A)
    await graph.refresh()
    updated = await manager.context(WORKSPACE_A, "columns")
    learning_nodes = [node for node in updated.nodes if node.kind is NodeKind.LEARNING]
    assert len(learning_nodes) == 1
    assert learning_nodes[0].ref.learning_id == 1
    assert learning_nodes[0].ref.run_id == "run-77"


async def test_accepted_and_rejected_artifact_versions_hydrate_with_lineage() -> None:
    artifacts = FakeArtifactSource()
    artifacts.versions.extend(
        [
            ArtifactVersionRecord(
                artifact_id="art-1",
                version="1",
                status="accepted",
                workspace_id=WORKSPACE_A,
                kind="banner",
                summary="Approved banner",
                run_id="run-1",
            ),
            ArtifactVersionRecord(
                artifact_id="art-1",
                version="2",
                status="rejected",
                workspace_id=WORKSPACE_A,
                kind="banner",
                summary="User rejected the gradient",
                run_id="run-2",
            ),
        ]
    )
    manager = WorkspaceWorkingMemoryManager(sources=[ArtifactHistorySource(artifacts)])
    context = await manager.context(WORKSPACE_A, "banner", hops=1)

    versions = {
        node.ref.artifact_version: node for node in context.nodes if node.kind is NodeKind.ARTIFACT
    }
    assert set(versions) == {"1", "2"}
    assert versions["1"].metadata["status"] == "accepted"
    assert versions["2"].metadata["status"] == "rejected"
    assert versions["2"].ref.artifact_id == "art-1"
    relations = {edge.relation for edge in context.edges}
    assert EdgeRelation.VERSION_OF in relations
    assert EdgeRelation.PRODUCED_DURING in relations


async def test_run_provenance_keeps_goal_and_parent_linkage() -> None:
    runs = FakeRunProvenanceSource()
    runs.runs.extend(
        [
            RunProvenanceRecord(
                run_id="run-1", workspace_id=WORKSPACE_A, goal_id="goal-1", status="completed"
            ),
            RunProvenanceRecord(
                run_id="run-2",
                workspace_id=WORKSPACE_A,
                goal_id="goal-1",
                parent_run_id="run-1",
                status="running",
                summary="revise hero banner",
            ),
        ]
    )
    episodic = InMemoryEpisodicStore()
    await episodic.store(make_memory("mem-5", "revise hero banner again", run_id="run-2"))
    manager = WorkspaceWorkingMemoryManager(
        sources=[
            DurableMemorySource(episodic=episodic, scope=SCOPE),
            RunProvenanceHydrationSource(runs),
        ]
    )
    walked = await manager.context(WORKSPACE_A, "revise hero banner", hops=2)

    # The memory produced during run-2 reaches run-2 and, one hop further,
    # its parent run-1 — the traversal Dreaming will need (#301/#1047).
    reached_runs = {node.ref.run_id for node in walked.nodes if node.kind is NodeKind.RUN}
    assert reached_runs == {"run-2", "run-1"}
    run_nodes = {node.ref.run_id: node for node in walked.nodes if node.kind is NodeKind.RUN}
    assert run_nodes["run-1"].ref.goal_id == "goal-1"
    follow_edges = [e for e in walked.edges if e.relation is EdgeRelation.FOLLOWS]
    assert follow_edges and follow_edges[0].dst_node_id == node_id_for(NodeKind.RUN, "run-1")


async def test_terminology_anchors_hydrate() -> None:
    terms = FakeTerminologySource()
    terms.terms.append(
        TerminologyRecord(
            term="moody",
            definition="low-key lighting, deep shadows",
            workspace_id=WORKSPACE_A,
        )
    )
    manager = WorkspaceWorkingMemoryManager(sources=[TerminologyHydrationSource(terms)])
    context = await manager.context(WORKSPACE_A, "moody")
    term_nodes = [node for node in context.nodes if node.kind is NodeKind.TERM]
    assert len(term_nodes) == 1
    assert term_nodes[0].content == "low-key lighting, deep shadows"
    assert "workspace_id=ws-aaaa" in context.to_text()


async def test_hydration_is_bounded(episodic: InMemoryEpisodicStore) -> None:
    for i in range(5):
        await episodic.store(make_memory(f"mem-{i}", f"note {i} about palettes"))
    manager = WorkspaceWorkingMemoryManager(
        sources=[BoundedDurableSource(episodic=episodic, scope=SCOPE)]
    )
    graph = await manager.graph(WORKSPACE_A)
    status = await graph.hydrate()
    assert status.node_count == 3  # the bounded source capped the collect at 3


async def test_embedded_backend_empty_query_is_newest_first_bounded_scan() -> None:
    backend = EmbeddedGraphBackend(WORKSPACE_A)
    old = WorkingGraphNode(
        node_id="memory:old",
        kind=NodeKind.MEMORY,
        label="old",
        workspace_id=WORKSPACE_A,
        ref=CanonicalRef(workspace_id=WORKSPACE_A),
        created_at=datetime.now(UTC) - timedelta(hours=1),
    )
    new = WorkingGraphNode(
        node_id="memory:new",
        kind=NodeKind.MEMORY,
        label="new",
        workspace_id=WORKSPACE_A,
        ref=CanonicalRef(workspace_id=WORKSPACE_A),
    )
    await backend.upsert_node(old)
    await backend.upsert_node(new)
    assert (await backend.search("", limit=1))[0].node_id == "memory:new"
    await backend.close()
