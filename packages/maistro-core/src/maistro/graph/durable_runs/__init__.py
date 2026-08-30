"""Durable canonical Graph execution state.

The canonical :class:`maistro.runs.model.Run` owns lifecycle and scope.
:class:`maistro.graph.execution_state.GraphExecutionState` owns only graph
traversal facts. This package persists the two together with chronological
canonical NodeRuns and Attempts so execution can resume after process loss.

The public durable execution entrypoints cross the canonical physical boundary
through ``Attempt -> AttemptExecutionService -> ExecutionRuntime`` while the
legacy traversal module remains the implementation home for Graph semantics.
"""

from __future__ import annotations

from maistro.runs.model import RunStatus

from .attempt_executor import (
    NodeResolver,
    resume_durable_graph,
    run_durable_graph,
)
from .canonical_store import CanonicalDurableRunStore
from .continuation import (
    GraphContinuation,
    GraphContinuationStore,
    InMemoryGraphContinuationStore,
    SqliteGraphContinuationStore,
)
from .execution_store import DurableRunExecutionStore
from .hitl import (
    HitlDeadlineElapsed,
    HitlDeadlinePending,
    HitlSettlementError,
    expire_hitl_pauses,
)
from .legacy_archive import (
    ArchivedGraphRun,
    LegacyGraphRunArchive,
    LegacyRunNotResumable,
)
from .protocol import DurableRunStore
from .stores import InMemoryDurableRunStore, SqliteDurableRunStore
from .types import DurableRunRecord

__all__ = [
    "ArchivedGraphRun",
    "CanonicalDurableRunStore",
    "DurableRunExecutionStore",
    "DurableRunRecord",
    "DurableRunStore",
    "GraphContinuation",
    "GraphContinuationStore",
    "HitlDeadlineElapsed",
    "HitlDeadlinePending",
    "HitlSettlementError",
    "InMemoryDurableRunStore",
    "InMemoryGraphContinuationStore",
    "LegacyGraphRunArchive",
    "LegacyRunNotResumable",
    "NodeResolver",
    "RunStatus",
    "SqliteDurableRunStore",
    "SqliteGraphContinuationStore",
    "expire_hitl_pauses",
    "resume_durable_graph",
    "run_durable_graph",
]
