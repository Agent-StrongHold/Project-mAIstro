"""Sandbox policy — determines minimum required isolation for a workload."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

IsolationTier = Literal["vm", "gvisor", "container", "bubblewrap", "fake"]

# Ordered from strongest to weakest
_TIER_ORDER: list[IsolationTier] = ["vm", "gvisor", "container", "bubblewrap", "fake"]


@dataclass(frozen=True)
class WorkloadPolicy:
    """What isolation a workload requires."""

    min_tier: IsolationTier
    network_allowed: bool = False
    max_memory_mb: int = 512
    max_timeout_s: int = 300
    reason: str = ""


# ─── Standard policies ────────────────────────────────────────────────────

UNTRUSTED_CODE = WorkloadPolicy(
    min_tier="vm",
    network_allowed=False,
    reason="Model-generated code must run behind a VM boundary",
)

TRUSTED_TOOL = WorkloadPolicy(
    min_tier="container",
    network_allowed=True,
    max_memory_mb=1024,
    reason="First-party tool with network access (e.g. Jira, web search)",
)

BENCHMARK_EVAL = WorkloadPolicy(
    min_tier="vm",
    network_allowed=False,
    max_timeout_s=600,
    reason="Benchmark execution runs untrusted candidate code",
)

BROWSER_AUTOMATION = WorkloadPolicy(
    min_tier="container",
    network_allowed=True,
    max_memory_mb=2048,
    reason="Browser needs egress; isolated from code sandbox",
)

DEV_ONLY = WorkloadPolicy(
    min_tier="fake",
    network_allowed=True,
    reason="Development/test only — no real isolation",
)


def tier_satisfies(available: IsolationTier, required: IsolationTier) -> bool:
    """Does the available tier meet or exceed the required tier?"""
    avail_idx = _TIER_ORDER.index(available)
    req_idx = _TIER_ORDER.index(required)
    return avail_idx <= req_idx  # Lower index = stronger
