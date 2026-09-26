"""Sandbox subsystem — protocol, policy, selector, backends."""

from maistro.sandbox.backends.container import (
    ContainerSandboxBackend,
    ContainerUnavailableError,
)
from maistro.sandbox.commit import fenced_commit
from maistro.sandbox.credential_boundary import (
    CANDIDATE_BASE_ENV,
    candidate_env,
    grant_from_credential,
    redact_env,
)
from maistro.sandbox.detect import HostCapabilities, detect_host_capabilities
from maistro.sandbox.fence import (
    SandboxFence,
    StaleExecutionFence,
    assert_fence_is_current,
    fence_from_context,
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
from maistro.sandbox.protocol import (
    DEFAULT_OUTPUT_CAPTURE_BYTES,
    MAX_OUTPUT_CAPTURE_BYTES,
    OUTPUT_LIMIT_EXIT_CODE,
    ExecResult,
    SandboxConfig,
    SandboxInstance,
    SandboxProtocol,
)
from maistro.sandbox.selector import (
    NoSuitableBackendError,
    SandboxSelector,
    TierMismatchError,
)
from maistro.sandbox.wiring import build_selector

__all__ = [
    "BENCHMARK_EVAL",
    "BROWSER_AUTOMATION",
    "CANDIDATE_BASE_ENV",
    "DEFAULT_OUTPUT_CAPTURE_BYTES",
    "DENY_ALL",
    "DEV_ONLY",
    "MAX_OUTPUT_CAPTURE_BYTES",
    "MODE_FLOORS",
    "OUTPUT_LIMIT_EXIT_CODE",
    "TRUSTED_TOOL",
    "UNTRUSTED_CODE",
    "ContainerSandboxBackend",
    "ContainerUnavailableError",
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
    "candidate_env",
    "detect_host_capabilities",
    "fence_from_context",
    "fenced_commit",
    "floor_for_mode",
    "grant_from_credential",
    "redact_env",
    "tier_satisfies",
]
