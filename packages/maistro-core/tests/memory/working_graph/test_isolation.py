"""Isolation: two Workspaces can never observe or traverse each other (#776).

The M3 bar is structural, not advisory: one graph per Workspace, separate
backend instances, records stamped with their owner, and refusals when a
mis-scoped record tries to cross. Colliding local identifiers — the same
memory id or the same entity label in two Workspaces — must stay two facts.
"""

from __future__ import annotations

import pytest

from maistro.memory.episodic.store import InMemoryEpisodicStore
from maistro.memory.working_graph import (
    DurableMemorySource,
    EmbeddedGraphBackend,
    ScopeSelection,
    WorkspaceWorkingMemoryManager,
)
from maistro.memory.working_graph.backend import create_backend, register_backend
from maistro.memory.working_graph.types import (
    BackendUnavailableError,
    CanonicalRef,
    ForeignWorkspaceError,
    NodeKind,
    WorkingGraphNode,
    node_id_for,
)

from .conftest import WORKSPACE_A, WORKSPACE_B, make_memory

SCOPE = ScopeSelection(org_id="org-1", team_id="team-1", user_id="user-1")


def _memory_node(memory_id: str, workspace_id: str, label: str) -> WorkingGraphNode:
    return WorkingGraphNode(
        node_id=node_id_for(NodeKind.MEMORY, memory_id),
        kind=NodeKind.MEMORY,
        label=label,
        workspace_id=workspace_id,
        ref=CanonicalRef(workspace_id=workspace_id, memory_id=memory_id),
    )


async def test_colliding_identifiers_stay_workspace_private() -> None:
    """The same memory id and label hydrate into both graphs; neither leaks."""
    episodic_a = InMemoryEpisodicStore()
    episodic_b = InMemoryEpisodicStore()
    await episodic_a.store(
        make_memory("mem-shared", "palette: slate and amber for the bakery brand")
    )
    await episodic_b.store(make_memory("mem-shared", "palette: matte black for the dev-tool brand"))

    class RoutingSource(DurableMemorySource):
        """One source serving two Workspaces from two durable stores."""

        def __init__(self) -> None:
            super().__init__(scope=SCOPE)
            self.routes = {WORKSPACE_A: episodic_a, WORKSPACE_B: episodic_b}

        async def collect(self, workspace_id: str, *, limit: int):  # type: ignore[override]
            self._episodic = self.routes[workspace_id]
            return await super().collect(workspace_id, limit=limit)

    # ONE manager, ONE source — isolation must come from the graph-per-
    # Workspace structure, not from who constructed the stores.
    manager = WorkspaceWorkingMemoryManager(sources=[RoutingSource()])

    context_a = await manager.context(WORKSPACE_A, "palette")
    context_b = await manager.context(WORKSPACE_B, "palette")

    assert [node.ref.memory_id for node in context_a.nodes] == ["mem-shared"]
    assert [node.ref.memory_id for node in context_b.nodes] == ["mem-shared"]
    assert "slate and amber" in context_a.nodes[0].content
    assert "matte black" in context_b.nodes[0].content
    # Every node is stamped with its owner; no cross-Workspace stamp exists.
    assert {node.workspace_id for node in context_a.nodes} == {WORKSPACE_A}
    assert {node.workspace_id for node in context_b.nodes} == {WORKSPACE_B}


async def test_one_graph_per_workspace_and_distinct_backends() -> None:
    built: list[str] = []

    def factory(workspace_id: str) -> EmbeddedGraphBackend:
        built.append(workspace_id)
        return EmbeddedGraphBackend(workspace_id)

    manager = WorkspaceWorkingMemoryManager(sources=[], backend_factory=factory)
    first = await manager.graph(WORKSPACE_A)
    second = await manager.graph(WORKSPACE_A)
    assert first is second  # exactly one graph per Workspace
    other = await manager.graph(WORKSPACE_B)
    assert other is not first
    assert built == [WORKSPACE_A, WORKSPACE_B]  # one backend instance each


async def test_backend_refuses_foreign_workspace_records() -> None:
    backend = EmbeddedGraphBackend(WORKSPACE_A)
    with pytest.raises(ForeignWorkspaceError):
        await backend.upsert_node(_memory_node("mem-x", WORKSPACE_B, "intruder"))
    assert await backend.counts() == (0, 0)


async def test_misscoped_hydration_cannot_poison_a_graph() -> None:
    """A source returning another Workspace's record is refused loudly."""

    class MisscopedSource(DurableMemorySource):
        async def collect(self, workspace_id: str, *, limit: int):  # type: ignore[override]
            snapshot = await super().collect(workspace_id, limit=limit)
            snapshot.nodes.append(_memory_node("mem-foreign", WORKSPACE_B, "smuggled"))
            return snapshot

    episodic = InMemoryEpisodicStore()
    await episodic.store(make_memory("mem-1", "honest local note"))
    manager = WorkspaceWorkingMemoryManager(
        sources=[MisscopedSource(episodic=episodic, scope=SCOPE)]
    )
    # Explicit hydration raises: a structural violation is not a degraded
    # read, it is a bug to fix.
    with pytest.raises(Exception, match="mem-foreign"):
        await (await manager.graph(WORKSPACE_A)).hydrate()
    # And the read path reports unavailable rather than serving a poisoned graph.
    context = await manager.context(WORKSPACE_A, "note")
    assert context.health.value in {"degraded", "unavailable"}


async def test_discarding_one_workspace_leaves_the_other_intact() -> None:
    episodic_a = InMemoryEpisodicStore()
    episodic_b = InMemoryEpisodicStore()
    await episodic_a.store(make_memory("mem-a", "workspace a fact"))
    await episodic_b.store(make_memory("mem-b", "workspace b fact"))
    manager = WorkspaceWorkingMemoryManager(
        sources=[DurableMemorySource(episodic=episodic_a, scope=SCOPE)]
    )
    manager_b = WorkspaceWorkingMemoryManager(
        sources=[DurableMemorySource(episodic=episodic_b, scope=SCOPE)]
    )
    await manager.context(WORKSPACE_A, "fact")
    await manager_b.context(WORKSPACE_B, "fact")

    await manager.discard(WORKSPACE_A)

    assert await manager.status(WORKSPACE_A) is None  # no graph anymore
    intact = await manager_b.context(WORKSPACE_B, "fact")
    assert [node.ref.memory_id for node in intact.nodes] == ["mem-b"]


def test_unknown_backend_name_is_an_explicit_refusal() -> None:
    with pytest.raises(BackendUnavailableError, match="ladybug"):
        create_backend("ladybug", WORKSPACE_A)


def test_registered_adapter_is_resolvable() -> None:
    seen: list[str] = []

    def adapter(workspace_id: str) -> EmbeddedGraphBackend:
        seen.append(workspace_id)
        return EmbeddedGraphBackend(workspace_id)

    register_backend("ladybug", adapter)
    try:
        backend = create_backend("ladybug", WORKSPACE_A)
        assert isinstance(backend, EmbeddedGraphBackend)
        assert seen == [WORKSPACE_A]
    finally:
        from maistro.memory.working_graph.backend import _BACKENDS

        _BACKENDS.pop("ladybug", None)
