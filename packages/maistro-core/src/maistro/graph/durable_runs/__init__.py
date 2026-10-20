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
    DEFAULT_MAX_STEPS,
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
from .fair_scan import ScanContinuation, cursor_time
from .hitl import (
    MAX_PENDING_SCAN_RECORDS,
    HitlAuthorization,
    HitlAuthorizationRequired,
    HitlDeadlineElapsed,
    HitlDeadlinePending,
    HitlDelegationEvidence,
    HitlSettlementError,
    PendingHitlScan,
    expire_hitl_pauses,
    pending_hitl_node_ids,
    pending_hitl_records,
)
from .launch import durable_graph_launch_provenance
from .legacy_archive import (
    ArchivedGraphRun,
    LegacyGraphRunArchive,
    LegacyRunNotResumable,
)
from .protocol import DurableRunStore, RecoveryInfrastructureError
from .recovery import recover_queued_graph_runs, resume_due_graph_runs
from .stores import InMemoryDurableRunStore, SqliteDurableRunStore
from .time_travel import (
    GraphStateEpoch,
    GraphStateLoad,
    SequenceOutOfRangeError,
    StateHistoryIntegrityError,
    UnknownGraphRunError,
)
from .types import DurableRunRecord

__all__ = [
    "DEFAULT_MAX_STEPS",
    "MAX_PENDING_SCAN_RECORDS",
    "ArchivedGraphRun",
    "CanonicalDurableRunStore",
    "DurableRunExecutionStore",
    "DurableRunRecord",
    "DurableRunStore",
    "GraphContinuation",
    "GraphContinuationStore",
    "GraphStateEpoch",
    "GraphStateLoad",
    "HitlAuthorization",
    "HitlAuthorizationRequired",
    "HitlDeadlineElapsed",
    "HitlDeadlinePending",
    "HitlDelegationEvidence",
    "HitlSettlementError",
    "InMemoryDurableRunStore",
    "InMemoryGraphContinuationStore",
    "LegacyGraphRunArchive",
    "LegacyRunNotResumable",
    "NodeResolver",
    "PendingHitlScan",
    "RecoveryInfrastructureError",
    "RunStatus",
    "ScanContinuation",
    "SequenceOutOfRangeError",
    "SqliteDurableRunStore",
    "SqliteGraphContinuationStore",
    "StateHistoryIntegrityError",
    "UnknownGraphRunError",
    "cursor_time",
    "durable_graph_launch_provenance",
    "expire_hitl_pauses",
    "pending_hitl_node_ids",
    "pending_hitl_records",
    "recover_queued_graph_runs",
    "resume_due_graph_runs",
    "resume_durable_graph",
    "run_durable_graph",
]
