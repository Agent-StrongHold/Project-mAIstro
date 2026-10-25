"""One working graph per active Workspace, and never two (#776).

The manager is the isolation authority for the working-memory seam:

- exactly one :class:`WorkspaceWorkingMemory` per ``workspace_id`` — a second
  ask returns the same graph, so a Workspace cannot race itself into two
  divergent projections;
- every graph gets its **own backend instance** (the factory is called per
  Workspace), so cross-Workspace traversal is structurally impossible: the
  other Workspace's records are simply absent from the graph you hold;
- graphs are evictable — the projection is disposable, so eviction is
  ``discard`` (backend ``close``), never a durable write.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Sequence

from maistro.memory.working_graph.backend import (
    BackendFactory,
    WorkingGraphBackend,
    create_backend,
)
from maistro.memory.working_graph.hydration import WorkingMemorySource
from maistro.memory.working_graph.store import WorkspaceWorkingMemory
from maistro.memory.working_graph.types import (
    GraphContext,
    WorkingMemoryError,
    WorkingMemoryHealth,
    WorkingMemoryStatus,
)

logger = logging.getLogger(__name__)


def _embedded_factory(workspace_id: str) -> WorkingGraphBackend:
    return create_backend("embedded", workspace_id)


class WorkspaceWorkingMemoryManager:
    """Owns the active Workspace→graph map for one process.

    M1 product-local projection: Workspace

    This is not the canonical Workspace model (owned by ``maistro.workspaces``):
    it is the working-memory domain's process-local map of which Workspace
    projections are currently materialised, and it holds no Workspace truth —
    every durable Workspace fact stays in the canonical stores.
    """

    def __init__(
        self,
        *,
        sources: Sequence[WorkingMemorySource],
        backend_factory: BackendFactory | None = None,
        max_active_graphs: int = 64,
    ) -> None:
        if max_active_graphs < 1:
            raise ValueError("max_active_graphs must be at least 1")
        self._sources = list(sources)
        self._backend_factory = backend_factory or _embedded_factory
        self._max_active_graphs = max_active_graphs
        self._graphs: OrderedDict[str, WorkspaceWorkingMemory] = OrderedDict()

    async def graph(self, workspace_id: str) -> WorkspaceWorkingMemory:
        """The one working graph for ``workspace_id``, created on first use."""
        if not workspace_id.strip():
            raise WorkingMemoryError("workspace_id must be a non-empty string")
        existing = self._graphs.get(workspace_id)
        if existing is not None:
            self._graphs.move_to_end(workspace_id)
            return existing
        await self._evict_overflow()
        graph = WorkspaceWorkingMemory(
            workspace_id=workspace_id,
            backend=self._backend_factory(workspace_id),
            sources=self._sources,
        )
        self._graphs[workspace_id] = graph
        return graph

    async def context(
        self,
        workspace_id: str,
        query: str,
        *,
        limit: int = 8,
        hops: int = 1,
    ) -> GraphContext:
        """Convenience read: the Workspace Agent's one call into the seam.

        Degradation is surfaced, never smoothed over: an impaired answer keeps
        its ``health``/``degraded_reason`` for the calling surface *and* is
        logged here, so operators see that working memory — never durable
        truth — is the impaired side.
        """
        graph = await self.graph(workspace_id)
        context = await graph.context(query, limit=limit, hops=hops)
        if context.health is not WorkingMemoryHealth.HEALTHY:
            logger.warning(
                "Working memory is %s for workspace %s while serving context: %s",
                context.health.value,
                workspace_id,
                context.degraded_reason or "no reason recorded",
            )
        return context

    async def status(self, workspace_id: str) -> WorkingMemoryStatus | None:
        """Status without creating a graph for a Workspace that has none."""
        graph = self._graphs.get(workspace_id)
        if graph is None:
            return None
        return await graph.status()

    async def discard(self, workspace_id: str) -> WorkingMemoryStatus:
        """Discard one Workspace's projection (it may be rebuilt at will)."""
        graph = self._graphs.pop(workspace_id, None)
        if graph is None:
            return WorkingMemoryStatus(
                workspace_id=workspace_id,
                health=WorkingMemoryHealth.COLD,
                backend="none",
            )
        status = await graph.discard()
        await graph.close()
        return status

    async def _evict_overflow(self) -> None:
        """Evict least-recently-used projections, oldest first.

        Eviction is disposal, not persistence: the ADR's whole point is that a
        working graph may vanish without durable loss, so eviction only closes
        the backend and drops the map entry.
        """
        while len(self._graphs) >= self._max_active_graphs:
            workspace_id, graph = self._graphs.popitem(last=False)
            logger.info("Evicting working graph for workspace %s", workspace_id)
            await graph.discard()
            await graph.close()


__all__ = ["WorkspaceWorkingMemoryManager"]
