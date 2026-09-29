"""Discard/rebuild and honest degradation (#776).

The projection must be disposable without durable loss, and a broken
projection must be reported as such — DEGRADED or UNAVAILABLE — while the
durable system of record stays intact and readable.
"""

from __future__ import annotations

from maistro.memory.episodic.store import InMemoryEpisodicStore
from maistro.memory.working_graph import (
    DurableMemorySource,
    EmbeddedGraphBackend,
    ScopeSelection,
    WorkspaceWorkingMemoryManager,
)
from maistro.memory.working_graph.types import (
    BackendUnavailableError,
    NodeKind,
    WorkingMemoryHealth,
)

from .conftest import WORKSPACE_A, ExplodingSource, make_memory

SCOPE = ScopeSelection(org_id="org-1", team_id="team-1", user_id="user-1")


class BrokenBackend(EmbeddedGraphBackend):
    """A projection that cannot answer — the degraded-path driver."""

    async def upsert_node(self, node):  # type: ignore[override]
        raise BackendUnavailableError("graph file is locked")


async def test_discard_and_rebuild_loses_no_durable_data(
    episodic: InMemoryEpisodicStore,
) -> None:
    await episodic.store(make_memory("mem-1", "poster drafts live in the archive"))
    manager = WorkspaceWorkingMemoryManager(
        sources=[DurableMemorySource(episodic=episodic, scope=SCOPE)]
    )
    before = await manager.context(WORKSPACE_A, "poster")
    assert len(before.nodes) == 1
    durable_before = await episodic.list_by_scope(org_id="org-1", limit=10)

    graph = await manager.graph(WORKSPACE_A)
    discarded = await graph.discard()
    assert discarded.health is WorkingMemoryHealth.COLD
    assert discarded.node_count == 0

    # Durable truth is untouched by discarding the projection.
    durable_after_discard = await episodic.list_by_scope(org_id="org-1", limit=10)
    assert [m.memory_id for m in durable_after_discard] == [m.memory_id for m in durable_before]

    rebuilt = await graph.hydrate(force=True)
    assert rebuilt.health is WorkingMemoryHealth.HEALTHY
    assert rebuilt.node_count == 1
    after = await manager.context(WORKSPACE_A, "poster")
    assert [node.ref.memory_id for node in after.nodes] == ["mem-1"]


async def test_unavailable_backend_reports_degraded_state_and_durable_intact(
    episodic: InMemoryEpisodicStore,
) -> None:
    await episodic.store(make_memory("mem-1", "the durable fact"))
    manager = WorkspaceWorkingMemoryManager(
        sources=[DurableMemorySource(episodic=episodic, scope=SCOPE)],
        backend_factory=lambda workspace_id: BrokenBackend(workspace_id),
    )

    context = await manager.context(WORKSPACE_A, "durable fact")
    assert context.health is WorkingMemoryHealth.UNAVAILABLE
    assert context.nodes == []  # never pretend memory is available
    assert "locked" in context.degraded_reason

    # The durable system of record is intact and still serves reads.
    durable = await episodic.list_by_scope(org_id="org-1", user_id="user-1", limit=10)
    assert [m.memory_id for m in durable] == ["mem-1"]


async def test_partial_source_failure_degrades_but_serves_the_rest(
    episodic: InMemoryEpisodicStore,
) -> None:
    await episodic.store(make_memory("mem-1", "hydration reaches this one"))
    manager = WorkspaceWorkingMemoryManager(
        sources=[
            DurableMemorySource(episodic=episodic, scope=SCOPE),
            ExplodingSource(error=RuntimeError("artifact store is down")),
        ]
    )
    context = await manager.context(WORKSPACE_A, "hydration")
    assert context.health is WorkingMemoryHealth.DEGRADED
    assert [node.ref.memory_id for node in context.nodes if node.kind is NodeKind.MEMORY] == [
        "mem-1"
    ]
    assert "ExplodingSource" in context.degraded_reason
    assert "artifact store is down" in context.degraded_reason

    status = await manager.status(WORKSPACE_A)
    assert status is not None
    assert status.health is WorkingMemoryHealth.DEGRADED
    assert status.last_error != ""


async def test_empty_sources_serve_no_invented_facts() -> None:
    manager = WorkspaceWorkingMemoryManager(sources=[])
    context = await manager.context(WORKSPACE_A, "anything at all")
    assert context.nodes == []
    assert context.health is WorkingMemoryHealth.HEALTHY  # honest emptiness
    assert "anything at all" not in context.to_text().split("workspace=")[-1]


async def test_closed_graph_reports_unavailable() -> None:
    manager = WorkspaceWorkingMemoryManager(sources=[])
    graph = await manager.graph(WORKSPACE_A)
    await graph.close()
    context = await graph.context("anything")
    assert context.health is WorkingMemoryHealth.UNAVAILABLE
    assert "closed" in context.degraded_reason


async def test_source_failure_degrades_explicitly_never_raises_into_readers() -> None:
    """A failing durable read is visible, not swallowed and not a crash."""
    manager = WorkspaceWorkingMemoryManager(
        sources=[ExplodingSource(error=RuntimeError("database unreachable"))]
    )
    graph = await manager.graph(WORKSPACE_A)
    status = await graph.hydrate()
    assert status.health is WorkingMemoryHealth.DEGRADED
    assert "ExplodingSource" in status.last_error
    assert "database unreachable" in status.last_error
    context = await graph.context("anything")
    assert context.health is WorkingMemoryHealth.DEGRADED
    assert context.nodes == []  # nothing was silently invented
