"""The per-Workspace working-memory facade: hydrate, query, discard.

One instance owns exactly one Workspace's working graph. Its contract, in the
order the issue states it:

- **Lazy**: the graph hydrates from durable sources on first use, not at
  construction.
- **Never authoritative**: every write path here touches only the working
  backend; the durable stores are opened strictly for reads.
- **Honest under failure**: a broken projection reports DEGRADED or
  UNAVAILABLE through :class:`WorkingMemoryHealth` — a read must never silently
  pretend memory is available while the durable system of record is fine.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Awaitable, Callable, Sequence
from functools import partial

from maistro.memory.working_graph.backend import WorkingGraphBackend
from maistro.memory.working_graph.hydration import (
    DEFAULT_HYDRATION_LIMIT,
    WorkingMemorySnapshot,
    WorkingMemorySource,
)
from maistro.memory.working_graph.types import (
    BackendUnavailableError,
    CanonicalRef,
    GraphContext,
    NodeKind,
    WorkingGraphEdge,
    WorkingGraphNode,
    WorkingMemoryError,
    WorkingMemoryHealth,
    WorkingMemoryStatus,
)

logger = logging.getLogger(__name__)

#: How many nodes one ``context()`` may return by default, before traversal
#: expansion. Retrieval-quality tuning is #301/M4; this is only a bound.
DEFAULT_CONTEXT_LIMIT = 8


def _run_anchors(snapshot: WorkingMemorySnapshot) -> list[WorkingGraphNode]:
    """Canonical RUN anchor nodes for edges whose Run was not projected."""
    present = {node.node_id for node in snapshot.nodes}
    anchors: list[WorkingGraphNode] = []
    seen: set[str] = set()
    prefix = f"{NodeKind.RUN.value}:"
    for edge in snapshot.edges:
        dst = edge.dst_node_id
        if not dst.startswith(prefix) or dst in present or dst in seen:
            continue
        seen.add(dst)
        run_id = dst[len(prefix) :]
        anchors.append(
            WorkingGraphNode(
                node_id=dst,
                kind=NodeKind.RUN,
                label=f"run {run_id}",
                workspace_id=snapshot.workspace_id,
                ref=CanonicalRef(workspace_id=snapshot.workspace_id, run_id=run_id),
                metadata={"anchor": True},
            )
        )
    return anchors


class WorkspaceWorkingMemory:
    """One Workspace's working graph, lazily hydrated, disposable."""

    def __init__(
        self,
        *,
        workspace_id: str,
        backend: WorkingGraphBackend,
        sources: Sequence[WorkingMemorySource],
    ) -> None:
        self.workspace_id = workspace_id
        self._backend = backend
        self._sources = list(sources)
        self._hydrated = False
        self._health = WorkingMemoryHealth.COLD
        self._last_error = ""
        self._closed = False

    # -- hydration ---------------------------------------------------------

    async def ensure_hydrated(self) -> None:
        if not self._hydrated:
            await self.hydrate()

    async def hydrate(self, *, force: bool = False) -> WorkingMemoryStatus:
        """(Re)hydrate the graph from durable sources.

        ``force=True`` first discards the projection, which is the whole
        rebuild story: durable truth is never consulted *through* the graph, so
        throwing the graph away cannot lose durable data. Upserts are
        idempotent, so a non-forced pass is an incremental refresh that picks
        up durably recorded corrections and newly accepted artifacts.
        """
        if self._closed:
            raise WorkingMemoryError(
                f"working memory for workspace {self.workspace_id!r} is closed"
            )
        if force:
            await self._guarded(self._backend.clear, what="clear")
        failures: list[str] = []
        for source in self._sources:
            try:
                snapshot = await source.collect(self.workspace_id, limit=DEFAULT_HYDRATION_LIMIT)
            except Exception as exc:
                # A failing durable read degrades the projection; it is the
                # durable system's incident, surfaced here, never swallowed.
                failures.append(f"{type(source).__name__}: {exc}")
                logger.warning(
                    "Working-memory source %s failed for workspace %s: %s",
                    type(source).__name__,
                    self.workspace_id,
                    exc,
                )
                continue
            for node in snapshot.nodes:
                self._assert_owned(node)
                await self._guarded(
                    partial(self._backend.upsert_node, node), what=f"upsert {node.node_id}"
                )
            # Edges may reference Runs the sources did not project as nodes
            # (e.g. a memory's producer Run). Synthesize the canonical RUN
            # anchor so the produced_during edge does not dangle; a fuller Run
            # node from another source upserts over the anchor, same id.
            for anchor in _run_anchors(snapshot):
                await self._guarded(
                    partial(self._backend.upsert_node, anchor),
                    what=f"upsert {anchor.node_id}",
                )
            for edge in snapshot.edges:
                self._assert_edge(edge)
                await self._guarded(
                    partial(self._backend.upsert_edge, edge), what=f"upsert {edge.edge_id}"
                )
        self._hydrated = True
        self._last_error = "; ".join(failures)
        self._health = WorkingMemoryHealth.DEGRADED if failures else WorkingMemoryHealth.HEALTHY
        return await self.status()

    # -- reads -------------------------------------------------------------

    async def context(
        self,
        query: str,
        *,
        limit: int = DEFAULT_CONTEXT_LIMIT,
        hops: int = 1,
    ) -> GraphContext:
        """Graph-backed context for this Workspace, or an honest degraded answer.

        The read path never raises for backend trouble: a Workspace Agent
        asking for context must receive either context that carries canonical
        references, or an explicitly degraded/UNAVAILABLE answer it can surface
        — never a confident fabrication from an empty graph.
        """
        if self._closed:
            return GraphContext(
                workspace_id=self.workspace_id,
                query=query,
                health=WorkingMemoryHealth.UNAVAILABLE,
                degraded_reason="working memory is closed",
            )
        try:
            await self.ensure_hydrated()
            matched = await self._backend.search(query, limit=max(limit, 0))
            selected: dict[str, WorkingGraphNode] = {node.node_id: node for node in matched}
            await self._expand_neighbours(selected, matched, hops)
            edges: list[WorkingGraphEdge] = []
            if selected:
                edges = await self._backend.edges_among(set(selected))
            return GraphContext(
                workspace_id=self.workspace_id,
                query=query,
                nodes=list(selected.values()),
                edges=edges,
                health=self._health,
                degraded_reason=self._last_error,
            )
        except BackendUnavailableError as exc:
            self._health = WorkingMemoryHealth.UNAVAILABLE
            self._last_error = str(exc)
            return self._degraded_context(query, str(exc))
        except Exception as exc:  # the read path degrades, always
            self._health = WorkingMemoryHealth.UNAVAILABLE
            self._last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("Working graph read failed for workspace %s: %s", self.workspace_id, exc)
            return self._degraded_context(query, self._last_error)

    async def _expand_neighbours(
        self,
        selected: dict[str, WorkingGraphNode],
        frontier: Sequence[WorkingGraphNode],
        hops: int,
    ) -> None:
        """Pull each neighbour of the matched set into ``selected``, ``hops``
        rounds deep. One backend read per edge, bounded by the hop cap the
        caller chose; the traversal cannot leave this Workspace's graph because
        the backend itself is per-Workspace (#776)."""
        for _ in range(max(hops, 0)):
            nxt: list[WorkingGraphNode] = []
            for node in frontier:
                for edge in await self._backend.edges_from(node.node_id):
                    neighbour = await self._backend.node(edge.dst_node_id)
                    if neighbour is not None and neighbour.node_id not in selected:
                        selected[neighbour.node_id] = neighbour
                        nxt.append(neighbour)
            frontier = nxt

    def _degraded_context(self, query: str, reason: str) -> GraphContext:
        return GraphContext(
            workspace_id=self.workspace_id,
            query=query,
            nodes=[],
            edges=[],
            health=self._health,
            degraded_reason=reason,
        )

    async def status(self) -> WorkingMemoryStatus:
        nodes, edges = 0, 0
        with contextlib.suppress(Exception):  # status must report, not raise
            nodes, edges = await self._guarded(self._backend.counts, what="counts")
        return WorkingMemoryStatus(
            workspace_id=self.workspace_id,
            health=self._health,
            backend=getattr(self._backend, "name", type(self._backend).__name__),
            node_count=nodes,
            edge_count=edges,
            last_error=self._last_error,
        )

    # -- lifecycle ---------------------------------------------------------

    async def discard(self) -> WorkingMemoryStatus:
        """Throw the projection away. Durable truth is untouched by design."""
        self._last_error = ""
        await self._guarded(self._backend.clear, what="clear")
        self._hydrated = False
        self._health = WorkingMemoryHealth.COLD
        return await self.status()

    async def close(self) -> None:
        await self._guarded(self._backend.close, what="close")
        self._closed = True
        self._health = WorkingMemoryHealth.UNAVAILABLE
        self._last_error = self._last_error or "working memory is closed"

    # -- guards ------------------------------------------------------------

    def _assert_owned(self, node: WorkingGraphNode) -> None:
        if node.workspace_id != self.workspace_id:
            # A mis-scoped source must never poison this graph: refuse loudly
            # at hydration time (the source read itself still succeeded).
            raise WorkingMemoryError(
                f"hydration produced node {node.node_id!r} for workspace "
                f"{node.workspace_id!r} while hydrating {self.workspace_id!r}"
            )

    def _assert_edge(self, edge: WorkingGraphEdge) -> None:
        if edge.workspace_id != self.workspace_id:
            raise WorkingMemoryError(
                f"hydration produced edge {edge.edge_id!r} for workspace "
                f"{edge.workspace_id!r} while hydrating {self.workspace_id!r}"
            )

    async def _guarded[T](self, operation: Callable[[], Awaitable[T]], *, what: str) -> T:
        """Await ``operation()``, translating backend trouble into degradation.

        ``operation`` is a zero-arg callable returning an awaitable so the
        try/except lives in exactly one place.
        """
        try:
            return await operation()
        except Exception as exc:
            self._health = WorkingMemoryHealth.UNAVAILABLE
            self._last_error = f"{what}: {exc}"
            raise
