"""The per-Workspace working-memory seam (#776, ADR-082226-5104).

Public surface for consumers (#773/#777, the persistent Workspace Agent, the
#301 Dreaming work):

- :class:`WorkspaceWorkingMemoryManager` — owns one isolated working graph per
  active Workspace; the entry point products hold.
- :class:`WorkspaceWorkingMemory` — one Workspace's graph: lazy hydration,
  ``context()`` queries, ``discard()``/rebuild.
- :class:`GraphContext` / :class:`WorkingMemoryHealth` — what a read returns;
  degradation is part of the answer, never silent.
- hydration sources (``DurableMemorySource``, ``ArtifactHistorySource``, …) —
  read-only projections of the durable stores; nothing here writes durable
  truth, because the working graph is never authoritative.
"""

from maistro.memory.working_graph.backend import (
    BackendFactory,
    EmbeddedGraphBackend,
    WorkingGraphBackend,
    WorkingGraphEdgeDangling,
    create_backend,
    register_backend,
)
from maistro.memory.working_graph.hydration import (
    ArtifactHistorySource,
    ArtifactSource,
    ArtifactVersionRecord,
    DurableMemorySource,
    RunProvenanceHydrationSource,
    RunProvenanceRecord,
    RunProvenanceSource,
    ScopeSelection,
    TerminologyHydrationSource,
    TerminologyRecord,
    TerminologySource,
    WorkingMemorySnapshot,
    WorkingMemorySource,
)
from maistro.memory.working_graph.manager import WorkspaceWorkingMemoryManager
from maistro.memory.working_graph.store import WorkspaceWorkingMemory
from maistro.memory.working_graph.types import (
    BackendUnavailableError,
    CanonicalRef,
    EdgeRelation,
    ForeignWorkspaceError,
    GraphContext,
    NodeKind,
    WorkingGraphEdge,
    WorkingGraphNode,
    WorkingMemoryError,
    WorkingMemoryHealth,
    WorkingMemoryStatus,
    node_id_for,
)

__all__ = [
    "ArtifactHistorySource",
    "ArtifactSource",
    "ArtifactVersionRecord",
    "BackendFactory",
    "BackendUnavailableError",
    "CanonicalRef",
    "DurableMemorySource",
    "EdgeRelation",
    "EmbeddedGraphBackend",
    "ForeignWorkspaceError",
    "GraphContext",
    "NodeKind",
    "RunProvenanceHydrationSource",
    "RunProvenanceRecord",
    "RunProvenanceSource",
    "ScopeSelection",
    "TerminologyHydrationSource",
    "TerminologyRecord",
    "TerminologySource",
    "WorkingGraphBackend",
    "WorkingGraphEdge",
    "WorkingGraphEdgeDangling",
    "WorkingGraphNode",
    "WorkingMemoryError",
    "WorkingMemoryHealth",
    "WorkingMemorySnapshot",
    "WorkingMemorySource",
    "WorkingMemoryStatus",
    "WorkspaceWorkingMemory",
    "WorkspaceWorkingMemoryManager",
    "create_backend",
    "node_id_for",
    "register_backend",
]
