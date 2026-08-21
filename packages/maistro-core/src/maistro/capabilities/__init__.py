"""Capability framework: slots, providers, bindings, invocations, and discovery."""

from __future__ import annotations

from maistro.capabilities.approval_store import (
    ApprovalStatus,
    DurableApproval,
    InMemoryApprovalStore,
    SqliteApprovalStore,
)
from maistro.capabilities.binding import Binding, ResolvedBinding
from maistro.capabilities.bootstrap import default_capability_registry
from maistro.capabilities.discovery import discover_into
from maistro.capabilities.governed_invocation import (
    GovernedInvocationExecutionService,
    InvocationApprovalPending,
    InvocationApprovalRequired,
    InvocationDenied,
    InvocationPolicyContext,
)
from maistro.capabilities.harness_manager import HarnessSessionManager
from maistro.capabilities.http import AsyncHttp
from maistro.capabilities.http_client import HttpxAsyncHttp
from maistro.capabilities.invocation import (
    CapabilityUnavailable,
    EffectNotApplied,
    InMemoryInvocationStore,
    Invocation,
    InvocationExecutionService,
    InvocationStatus,
    UnsafeEffectRetry,
)
from maistro.capabilities.invocation_store import SqliteInvocationStore
from maistro.capabilities.protocols import CapabilityProvider
from maistro.capabilities.providers.harness_safety import (
    ActionGate,
    AllowAllGate,
    SafeHarnessRunner,
)
from maistro.capabilities.providers.opencode import (
    OpencodeHarnessRunner,
    opencode_microvm_factory,
    opencode_microvm_runner,
)
from maistro.capabilities.providers.subprocess_harness import (
    SandboxExec,
    SubprocessHarnessRunner,
)
from maistro.capabilities.registry import CapabilityRegistry
from maistro.capabilities.slots.harness import (
    HARNESS_RUNNER_SLOT,
    GuardedHarnessRunner,
    resolve_harness_runner,
)
from maistro.capabilities.slots.harness_runner import (
    HarnessInputBlocked,
    HarnessRunner,
)
from maistro.capabilities.types import (
    FallbackPolicy,
    ProviderHealth,
    SlotSpec,
    Unavailable,
)

__all__ = [
    "HARNESS_RUNNER_SLOT",
    "ActionGate",
    "AllowAllGate",
    "ApprovalStatus",
    "AsyncHttp",
    "Binding",
    "CapabilityProvider",
    "CapabilityRegistry",
    "CapabilityUnavailable",
    "DurableApproval",
    "EffectNotApplied",
    "FallbackPolicy",
    "GovernedInvocationExecutionService",
    "GuardedHarnessRunner",
    "HarnessInputBlocked",
    "HarnessRunner",
    "HarnessSessionManager",
    "HttpxAsyncHttp",
    "InMemoryApprovalStore",
    "InMemoryInvocationStore",
    "Invocation",
    "InvocationApprovalPending",
    "InvocationApprovalRequired",
    "InvocationDenied",
    "InvocationExecutionService",
    "InvocationPolicyContext",
    "InvocationStatus",
    "OpencodeHarnessRunner",
    "ProviderHealth",
    "ResolvedBinding",
    "SafeHarnessRunner",
    "SandboxExec",
    "SlotSpec",
    "SqliteApprovalStore",
    "SqliteInvocationStore",
    "SubprocessHarnessRunner",
    "Unavailable",
    "UnsafeEffectRetry",
    "default_capability_registry",
    "discover_into",
    "opencode_microvm_factory",
    "opencode_microvm_runner",
    "resolve_harness_runner",
]
