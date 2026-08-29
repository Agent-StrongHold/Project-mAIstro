"""Sandbox subsystem — protocol, policy, selector, backends."""

from maistro.sandbox.detect import HostCapabilities, detect_host_capabilities
from maistro.sandbox.policy import (
    BENCHMARK_EVAL,
    BROWSER_AUTOMATION,
    DEV_ONLY,
    TRUSTED_TOOL,
    UNTRUSTED_CODE,
    WorkloadPolicy,
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
    "DEV_ONLY",
    "TRUSTED_TOOL",
    "UNTRUSTED_CODE",
    "ExecResult",
    "HostCapabilities",
    "NoSuitableBackendError",
    "SandboxConfig",
    "SandboxInstance",
    "SandboxProtocol",
    "SandboxSelector",
    "TierMismatchError",
    "WorkloadPolicy",
    "build_selector",
    "detect_host_capabilities",
    "tier_satisfies",
]
