"""The working-graph backend port and the embedded reference backend.

LadybugDB (ADR-082226-5104 §5) is the chosen working-memory engine: embedded,
in-process, ``:memory:`` by preference, one graph per active Workspace, never
authoritative. The ``ladybugdb`` distribution is not published to this
environment's package registry (checked), so the engine ships the **port** —
the seam #773/#777 and the persistent Workspace Agent code against — plus an
executable embedded reference backend with the same disposition (in-process,
disposable, single-Workspace). A Ladybug adapter registers against
:func:`register_backend` once the package is installable; nothing else in the
engine may grow a second graph stack.

The port is deliberately small. Backends must stay replaceable projections:
anything a backend cannot answer honestly must surface as an exception rather
than as plausible empty results.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from maistro.memory.working_graph.types import (
    BackendUnavailableError,
    ForeignWorkspaceError,
    WorkingGraphEdge,
    WorkingGraphNode,
    WorkingMemoryError,
)

#: Factory signature: the backend is constructed per Workspace so that two
#: Workspaces can never share physical working state.
BackendFactory = Callable[[str], "WorkingGraphBackend"]

_BACKENDS: dict[str, BackendFactory] = {}


class WorkingGraphEdgeDangling(WorkingMemoryError):
    """An edge referenced nodes this graph does not hold."""


def register_backend(name: str, factory: BackendFactory) -> None:
    """Register a named backend factory (the Ladybug adapter's entry point)."""
    _BACKENDS[name] = factory


def create_backend(name: str, workspace_id: str) -> WorkingGraphBackend:
    """Build the named backend for one Workspace.

    ``embedded`` is the shipped reference backend. Any other name resolves
    through :func:`register_backend`; an unregistered name raises
    :class:`BackendUnavailableError` — an explicit, surfaced refusal, which the
    working-memory store turns into a degraded state rather than a silent
    substitute.
    """
    if name == "embedded":
        return EmbeddedGraphBackend(workspace_id)
    factory = _BACKENDS.get(name)
    if factory is None:
        raise BackendUnavailableError(
            f"working-graph backend {name!r} is not available "
            f"(registered: {sorted(_BACKENDS)} plus 'embedded')"
        )
    return factory(workspace_id)


@runtime_checkable
class WorkingGraphBackend(Protocol):
    """One Workspace's isolated working graph.

    Implementations must refuse nodes/edges whose ``workspace_id`` differs from
    the graph's owner: the isolation guarantee is structural (the other
    Workspace's records are simply absent), and the refusal is the tripwire
    that catches a mis-scoped hydration source before it poisons a graph.
    """

    async def upsert_node(self, node: WorkingGraphNode) -> None: ...

    async def upsert_edge(self, edge: WorkingGraphEdge) -> None: ...

    async def node(self, node_id: str) -> WorkingGraphNode | None: ...

    async def search(self, query: str, *, limit: int) -> list[WorkingGraphNode]: ...

    async def edges_among(self, node_ids: set[str]) -> list[WorkingGraphEdge]: ...

    async def edges_from(self, node_id: str) -> list[WorkingGraphEdge]: ...

    async def counts(self) -> tuple[int, int]: ...

    async def clear(self) -> None: ...

    async def close(self) -> None: ...


_STRIPPABLE = ".,;:!?()[]{}\"'"


def _tokens(text: str) -> set[str]:
    """Lowercased word tokens, the floor retrieval strategy for M3.

    Optimising retrieval (BM25, vectors, graph walk scoring) is explicitly
    deferred to #301/M4; the floor only needs honest lexical overlap.
    """
    return {stripped for token in text.lower().split() if (stripped := token.strip(_STRIPPABLE))}


class EmbeddedGraphBackend:
    """In-process reference working graph.

    Stated disposition: this is what LadybugDB's ``:memory:`` mode provides in
    kind — embedded, per-Workspace, disposable, non-authoritative — standing in
    until the ``ladybugdb`` distribution is installable. Its data lives exactly
    as long as this object does; nothing here is durable.
    """

    def __init__(self, workspace_id: str) -> None:
        self.workspace_id = workspace_id
        self.name = "embedded"
        self._nodes: dict[str, WorkingGraphNode] = {}
        self._edges: dict[str, WorkingGraphEdge] = {}
        self._outgoing: dict[str, set[str]] = defaultdict(set)

    def _require_owned(self, workspace_id: str) -> None:
        if workspace_id != self.workspace_id:
            raise ForeignWorkspaceError(
                f"working graph {self.workspace_id!r} was handed a record "
                f"for workspace {workspace_id!r}"
            )

    async def upsert_node(self, node: WorkingGraphNode) -> None:
        self._require_owned(node.workspace_id)
        self._nodes[node.node_id] = node

    async def upsert_edge(self, edge: WorkingGraphEdge) -> None:
        self._require_owned(edge.workspace_id)
        # An edge must not dangle: both endpoints must already be in this
        # graph. Hydration is per-Workspace, so a dangling edge would mean a
        # source produced a cross-Workspace or phantom relation.
        if edge.src_node_id not in self._nodes or edge.dst_node_id not in self._nodes:
            raise WorkingGraphEdgeDangling(
                f"edge {edge.edge_id!r} references nodes outside graph {self.workspace_id!r}"
            )
        self._edges[edge.edge_id] = edge
        self._outgoing[edge.src_node_id].add(edge.edge_id)

    async def node(self, node_id: str) -> WorkingGraphNode | None:
        return self._nodes.get(node_id)

    async def search(self, query: str, *, limit: int) -> list[WorkingGraphNode]:
        """Lexical-overlap retrieval over label and content.

        An empty query is a bounded scan request, not a match-all ranking: it
        returns the newest nodes so a caller asking for "whatever is hot"
        still gets a deterministic, bounded answer.
        """
        query_tokens = _tokens(query)
        if not query_tokens:
            ranked = sorted(self._nodes.values(), key=lambda node: node.created_at, reverse=True)
            return ranked[: max(limit, 0)]
        scored: list[tuple[float, WorkingGraphNode]] = []
        for node in self._nodes.values():
            node_tokens = _tokens(f"{node.label} {node.content}")
            if not node_tokens:
                continue
            overlap = len(query_tokens & node_tokens) / len(query_tokens)
            if overlap > 0:
                scored.append((overlap, node))
        scored.sort(key=lambda pair: (-pair[0], pair[1].node_id))
        return [node for _, node in scored[: max(limit, 0)]]

    async def edges_among(self, node_ids: set[str]) -> list[WorkingGraphEdge]:
        return [
            edge
            for edge in self._edges.values()
            if edge.src_node_id in node_ids and edge.dst_node_id in node_ids
        ]

    async def edges_from(self, node_id: str) -> list[WorkingGraphEdge]:
        return [self._edges[edge_id] for edge_id in sorted(self._outgoing.get(node_id, ()))]

    async def counts(self) -> tuple[int, int]:
        return len(self._nodes), len(self._edges)

    async def clear(self) -> None:
        self._nodes.clear()
        self._edges.clear()
        self._outgoing.clear()

    async def close(self) -> None:
        await self.clear()


__all__ = [
    "BackendFactory",
    "EmbeddedGraphBackend",
    "WorkingGraphBackend",
    "WorkingGraphEdgeDangling",
    "create_backend",
    "register_backend",
]
