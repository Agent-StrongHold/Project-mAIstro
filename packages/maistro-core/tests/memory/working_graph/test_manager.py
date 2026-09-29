"""Manager lifecycle: one graph per Workspace, evictable, disposable (#776)."""

from __future__ import annotations

from maistro.memory.working_graph import (
    EmbeddedGraphBackend,
    WorkspaceWorkingMemoryManager,
)
from maistro.memory.working_graph.types import WorkingMemoryError, WorkingMemoryHealth

from .conftest import WORKSPACE_A, WORKSPACE_B


async def test_status_is_none_for_unknown_workspace() -> None:
    manager = WorkspaceWorkingMemoryManager(sources=[])
    assert await manager.status("no-such-workspace") is None


async def test_blank_workspace_id_is_refused() -> None:
    manager = WorkspaceWorkingMemoryManager(sources=[])
    try:
        await manager.graph("   ")
    except WorkingMemoryError:
        pass
    else:
        raise AssertionError("blank workspace_id must be refused")


async def test_lru_eviction_discards_oldest_graph() -> None:
    built: dict[str, EmbeddedGraphBackend] = {}

    def build(workspace_id: str) -> EmbeddedGraphBackend:
        backend = EmbeddedGraphBackend(workspace_id)
        built[workspace_id] = backend
        return backend

    manager = WorkspaceWorkingMemoryManager(sources=[], backend_factory=build, max_active_graphs=2)
    await manager.graph(WORKSPACE_A)
    await manager.graph(WORKSPACE_B)
    assert manager.active_workspaces() == [WORKSPACE_A, WORKSPACE_B]

    # Touch A so B becomes the least recently used, then force one eviction.
    await manager.graph(WORKSPACE_A)
    await manager.graph("ws-cccc")

    assert manager.active_workspaces() == [WORKSPACE_A, "ws-cccc"]
    assert await manager.status(WORKSPACE_B) is None
    # Eviction is disposal: the evicted graph's backend holds nothing.
    assert await built[WORKSPACE_B].counts() == (0, 0)


async def test_discard_all_clears_every_projection() -> None:
    manager = WorkspaceWorkingMemoryManager(
        sources=[],
        backend_factory=lambda workspace_id: EmbeddedGraphBackend(workspace_id),
        max_active_graphs=8,
    )
    await manager.graph(WORKSPACE_A)
    await manager.graph(WORKSPACE_B)
    assert len(manager.active_workspaces()) == 2

    assert await manager.discard_all() == 2
    assert manager.active_workspaces() == []
    assert await manager.status(WORKSPACE_A) is None
    assert await manager.status(WORKSPACE_B) is None


async def test_discard_of_unknown_workspace_reports_cold_not_error() -> None:
    manager = WorkspaceWorkingMemoryManager(sources=[])
    status = await manager.discard("never-existed")
    assert status.health is WorkingMemoryHealth.COLD
    assert status.backend == "none"
