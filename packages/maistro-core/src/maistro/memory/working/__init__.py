"""Per-Workspace working-memory projection (ADR-082226-5104).

PostgreSQL + pgvector is the authoritative durable memory; the working-memory
projection in this package is the disposable per-active-Workspace hot layer the
ADR names. MAIstro owns the protocol and the invariants: the projection never
becomes a second system of record, never widens scope visibility, and can be
discarded and rebuilt from the authoritative store with no durable loss.
"""

from __future__ import annotations

from maistro.memory.working.dreaming import DreamingCandidateSet, collect_candidates
from maistro.memory.working.extraction import (
    EntityExtractor,
    GovernedEntityExtractor,
    LexicalEntityExtractor,
)
from maistro.memory.working.manager import WorkingMemoryError, WorkingMemoryManager
from maistro.memory.working.projection import WorkspaceWorkingMemoryProjection
from maistro.memory.working.protocol import (
    DEFAULT_EMBEDDING_MODEL,
    EntityContext,
    EntityRecord,
    HydrationReport,
    RelationRecord,
    ScoredWorkingMemory,
    TraversalResult,
    WorkingMemory,
    WorkingMemoryStats,
)

__all__ = [
    "DEFAULT_EMBEDDING_MODEL",
    "DreamingCandidateSet",
    "EntityContext",
    "EntityExtractor",
    "EntityRecord",
    "GovernedEntityExtractor",
    "HydrationReport",
    "LexicalEntityExtractor",
    "RelationRecord",
    "ScoredWorkingMemory",
    "TraversalResult",
    "WorkingGraphCandidates",
    "WorkingMemory",
    "WorkingMemoryError",
    "WorkingMemoryManager",
    "WorkingMemoryStats",
    "WorkspaceWorkingMemoryProjection",
    "collect_candidates",
]
