"""Durable log-as-context and measured per-Workspace working memory (M4-H, #301).

The append-only observation log (:mod:`maistro.memory.working.store` and its
SQLite twin) is the system of record; the per-Workspace projection
(:mod:`maistro.memory.working.projection`) is the disposable Ladybug-role
working graph hydrated from it (ADR-082226-5104 §5-6); recall, the GUIDE and
WORKING prompt representations, simplification/resets and the redundancy and
fresh-vs-lineage measurements are derivations over that log.
"""

from __future__ import annotations

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
    "FreshVsLineageMeasurement",
    "InMemoryWorkspaceLogStore",
    "ObservationKind",
    "ProjectionStats",
    "RecallHit",
    "RedundantHypothesisMeasurement",
    "RenderedWorkingContext",
    "WorkingMemoryManager",
    "WorkingMemoryRecall",
    "WorkingResult",
    "WorkspaceLogStore",
    "WorkspaceObservation",
    "WorkspaceWorkingMemory",
    "append_cycle_summary",
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
