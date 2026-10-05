"""A2A (Agent-to-Agent) delegation — public surface (ADR-058, SPEC-182).

One delegation protocol behind :class:`A2ABroker`. Phases 1-2 (export surface,
lifecycle fixes, budgets, local transport) are implemented; the federated
transport is Phase 3 follow-up. ``WorkerPool``/``TaskLifecycleManager`` are
experimental (ADR-058 resolved decision 2).
"""

from maistro.a2a.broker import (
    A2ABroker,
    A2AError,
    AgentInvoker,
    CardResolver,
    DelegationBudget,
    DelegationRefused,
    LocalTransport,
    Transport,
)
from maistro.a2a.delegate import A2ADelegator, A2ATask, DelegationMode, TaskStatus
from maistro.a2a.guest_peers import (
    AuditLogger,
    DelegationResult,
    GuestPeerManager,
    InMemoryAuditLogger,
    PeerTrust,
)
from maistro.a2a.lifecycle import TaskLifecycleManager, TaskQueue, WorkerConfig, WorkerPool
from maistro.a2a.normalize import (
    CancellationProjection,
    CanonicalDelegationTruth,
    RemoteLifecycleState,
    RemoteProgressObservation,
    RemoteRetryDecision,
    RetryDecision,
    SettlementDecision,
    decide_cancellation,
    decide_retry,
    decide_settlement,
    normalize_remote_state,
    record_progress,
    settle_outcome,
)

__all__ = [
    "A2ABroker",
    "A2ADelegator",
    "A2AError",
    "A2ATask",
    "AgentInvoker",
    "AuditLogger",
    "CancellationProjection",
    "CanonicalDelegationTruth",
    "CardResolver",
    "DelegationBudget",
    "DelegationMode",
    "DelegationRefused",
    "DelegationResult",
    "GuestPeerManager",
    "InMemoryAuditLogger",
    "LocalTransport",
    "PeerTrust",
    "RemoteLifecycleState",
    "RemoteProgressObservation",
    "RemoteRetryDecision",
    "RetryDecision",
    "SettlementDecision",
    "TaskLifecycleManager",
    "TaskQueue",
    "TaskStatus",
    "Transport",
    "WorkerConfig",
    "WorkerPool",
    "decide_cancellation",
    "decide_retry",
    "decide_settlement",
    "normalize_remote_state",
    "record_progress",
    "settle_outcome",
]
