"""Sandbox subsystem — protocol, policy, selector, backends."""

from maistro.sandbox.commit import fenced_commit
from maistro.sandbox.detect import HostCapabilities, detect_host_capabilities
from maistro.sandbox.fence import (
    SandboxFence,
    StaleExecutionFence,
    assert_fence_is_current,
)
from maistro.sandbox.network import (
    DENY_ALL,
    EgressGrant,
    EgressMode,
    EgressNotEnforceableError,
)
from maistro.sandbox.policy import (
    BENCHMARK_EVAL,
    BROWSER_AUTOMATION,
    DEV_ONLY,
    MODE_FLOORS,
    TRUSTED_TOOL,
    UNTRUSTED_CODE,
    ExecutionMode,
    WorkloadPolicy,
    floor_for_mode,
    tier_satisfies,
)
from maistro.sandbox.protocol import ExecResult, SandboxConfig, SandboxInstance, SandboxProtocol
from maistro.sandbox.selector import (
    NoSuitableBackendError,
    SandboxSelector,
    TierMismatchError,
)
from maistro.sandbox.wiring import build_selector

__all__ = [
    "BENCHMARK_EVAL",
    "BROWSER_AUTOMATION",
    "DENY_ALL",
    "DEV_ONLY",
    "MODE_FLOORS",
    "TRUSTED_TOOL",
    "UNTRUSTED_CODE",
    "EgressGrant",
    "EgressMode",
    "EgressNotEnforceableError",
    "ExecResult",
    "ExecutionMode",
    "HostCapabilities",
    "NoSuitableBackendError",
    "SandboxConfig",
    "SandboxFence",
    "SandboxInstance",
    "SandboxProtocol",
    "SandboxSelector",
    "StaleExecutionFence",
    "TierMismatchError",
    "WorkloadPolicy",
    "assert_fence_is_current",
    "build_selector",
    "detect_host_capabilities",
    "fenced_commit",
    "floor_for_mode",
    "tier_satisfies",
]
