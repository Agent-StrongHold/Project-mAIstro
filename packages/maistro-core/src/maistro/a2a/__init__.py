"""A2A (Agent-to-Agent) delegation — public surface (ADR-058, SPEC-182).

One delegation protocol behind :class:`A2ABroker`. Phases 1-2 (export surface,
lifecycle fixes, budgets, local transport) are implemented; the federated
transport is Phase 3 follow-up. ``WorkerPool``/``TaskLifecycleManager`` are
experimental (ADR-058 resolved decision 2).

External Agent discovery (M9-D1, #958) exports the descriptor/card adapter and
the canonical capability projection (:mod:`maistro.a2a.external`): external
descriptors are ingested as *data*, projected through policy, and never become
a second Agent-definition authority.
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
from maistro.a2a.external import (
    EXTERNAL_PRIORITY_TIER,
    EXTERNAL_TRUST_TIER,
    AuthorityEscalationRefused,
    Availability,
    AvailabilityState,
    CapabilityAuthorization,
    DefaultDenyProjectionPolicy,
    DescriptorAlreadyRegistered,
    DescriptorError,
    DescriptorInvalid,
    DescriptorProvenance,
    EndpointConflict,
    ExternalAgentRegistry,
    ProjectionPolicy,
    RegisteredExternalAgent,
    RemoteAgentDescriptor,
    RemoteCapabilities,
    SpecialistProjection,
    UnknownExternalAgent,
    UnsupportedCapability,
    parse_remote_card,
    payload_digest,
)
from maistro.a2a.guest_peers import (
    AuditLogger,
    DelegationResult,
    GuestPeerManager,
    InMemoryAuditLogger,
    PeerTrust,
)
from maistro.a2a.lifecycle import TaskLifecycleManager, TaskQueue, WorkerConfig, WorkerPool

__all__ = [
    "EXTERNAL_PRIORITY_TIER",
    "EXTERNAL_TRUST_TIER",
    "A2ABroker",
    "A2ADelegator",
    "A2AError",
    "A2ATask",
    "AgentInvoker",
    "AuditLogger",
    "AuthorityEscalationRefused",
    "Availability",
    "AvailabilityState",
    "CapabilityAuthorization",
    "CardResolver",
    "DefaultDenyProjectionPolicy",
    "DelegationBudget",
    "DelegationMode",
    "DelegationRefused",
    "DelegationResult",
    "DescriptorAlreadyRegistered",
    "DescriptorError",
    "DescriptorInvalid",
    "DescriptorProvenance",
    "EndpointConflict",
    "ExternalAgentRegistry",
    "GuestPeerManager",
    "InMemoryAuditLogger",
    "LocalTransport",
    "PeerTrust",
    "ProjectionPolicy",
    "RegisteredExternalAgent",
    "RemoteAgentDescriptor",
    "RemoteCapabilities",
    "SpecialistProjection",
    "TaskLifecycleManager",
    "TaskQueue",
    "TaskStatus",
    "Transport",
    "UnknownExternalAgent",
    "UnsupportedCapability",
    "WorkerConfig",
    "WorkerPool",
    "parse_remote_card",
    "payload_digest",
]
