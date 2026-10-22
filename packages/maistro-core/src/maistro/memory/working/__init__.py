"""Per-Workspace working memory (M4-H / #301, ADR-082226-5104).

Two cooperating halves, neither authoritative:

* the append-only observation log (:mod:`maistro.memory.working.store` and
  its SQLite twin) is the durable system of record for working observations;
  the per-Workspace projection over it (:mod:`maistro.memory.working.projection`)
  is the disposable Ladybug-role working graph hydrated from that log —
  recall, the GUIDE and WORKING prompt representations, simplification/resets
  and the redundancy and fresh-vs-lineage measurements are derivations over it;
* the indexed hot projection (:mod:`maistro.memory.working.indexed`) is the
  first :class:`~maistro.memory.working.protocol.WorkingMemory` implementation:
  BM25 over a tokenised inverted index, embeddings stored at write time, and
  an entity graph with ``MentionedIn`` and co-occurrence edges, hydrated from
  the authoritative episodic store. The protocol is the adoption seam a
  LadybugDB-backed adapter will take; the patterns reused from the
  Ladybug-Memory design are recorded in ``INSPIRATIONS.md``.

MAIstro owns the protocol and the invariants: neither half ever becomes a
second system of record, neither widens scope visibility, and both can be
discarded and rebuilt from their durable sources with no durable loss.
"""

from __future__ import annotations

from maistro.memory.working.dreaming import DreamingCandidateSet, collect_candidates
from maistro.memory.working.extraction import (
    EntityExtractor,
    GovernedEntityExtractor,
    LexicalEntityExtractor,
)
from maistro.memory.working.indexed import WorkspaceWorkingMemoryProjection
from maistro.memory.working.manager import (
    WorkingMemoryError,
)
from maistro.memory.working.manager import (
    WorkingMemoryManager as HotWorkingMemoryManager,
)
from maistro.memory.working.measurement import (
    FreshVsLineageMeasurement,
    RedundantHypothesisMeasurement,
    measure_fresh_vs_lineage,
    measure_redundant_hypotheses,
)
from maistro.memory.working.projection import (
    ProjectionStats,
    WorkingMemoryManager,
    WorkspaceWorkingMemory,
)
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
from maistro.memory.working.recall import RecallHit, WorkingMemoryRecall
from maistro.memory.working.render import (
    RenderedWorkingContext,
    render_guide,
    render_working,
    render_working_context,
)
from maistro.memory.working.simplify import (
    append_cycle_summary,
    hard_reset,
    simplify,
)
from maistro.memory.working.store import (
    InMemoryWorkspaceLogStore,
    WorkspaceLogStore,
)
from maistro.memory.working.types import (
    ObservationKind,
    WorkingResult,
    WorkspaceObservation,
    content_digest,
    make_result_id,
    observation,
    reset_entry,
    summary_entry,
)

__all__ = [
    "DEFAULT_EMBEDDING_MODEL",
    "DreamingCandidateSet",
    "EntityContext",
    "EntityExtractor",
    "EntityRecord",
    "FreshVsLineageMeasurement",
    "GovernedEntityExtractor",
    "HotWorkingMemoryManager",
    "HydrationReport",
    "InMemoryWorkspaceLogStore",
    "LexicalEntityExtractor",
    "ObservationKind",
    "ProjectionStats",
    "RecallHit",
    "RedundantHypothesisMeasurement",
    "RelationRecord",
    "RenderedWorkingContext",
    "ScoredWorkingMemory",
    "TraversalResult",
    "WorkingMemory",
    "WorkingMemoryError",
    "WorkingMemoryManager",
    "WorkingMemoryRecall",
    "WorkingMemoryStats",
    "WorkingResult",
    "WorkspaceLogStore",
    "WorkspaceObservation",
    "WorkspaceWorkingMemory",
    "WorkspaceWorkingMemoryProjection",
    "append_cycle_summary",
    "collect_candidates",
    "content_digest",
    "hard_reset",
    "make_result_id",
    "measure_fresh_vs_lineage",
    "measure_redundant_hypotheses",
    "observation",
    "render_guide",
    "render_working",
    "render_working_context",
    "reset_entry",
    "simplify",
    "summary_entry",
]
