"""Sandbox policy — determines minimum required isolation for a workload."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from maistro.sandbox.network import DENY_ALL, EgressGrant, EgressMode

IsolationTier = Literal["vm", "gvisor", "container", "bubblewrap", "fake"]

# Ordered from strongest to weakest
_TIER_ORDER: list[IsolationTier] = ["vm", "gvisor", "container", "bubblewrap", "fake"]


class ExecutionMode(StrEnum):
    """Whether a human is watching (ADR-093 decision 6)."""

    #: A person at the keyboard, with SPEC-200 confirmation gates live.
    INTERACTIVE = "interactive"
    #: Unattended: builders pipelines, scheduled DAG nodes, benchmark harnesses
    #: — anything with nobody watching.
    AUTONOMOUS = "autonomous"


#: The *floor* each mode imposes, independent of what the workload asked for.
#: ADR-093's table: interactive may proceed on Tier 3, autonomous may not.
MODE_FLOORS: dict[ExecutionMode, IsolationTier] = {
    ExecutionMode.INTERACTIVE: "bubblewrap",
    ExecutionMode.AUTONOMOUS: "gvisor",
}


def floor_for_mode(mode: ExecutionMode | None) -> IsolationTier:
    """An unknown or unstated mode gets the autonomous floor.

    ADR-093 says so explicitly, and the reason is the asymmetry of being wrong:
    treating an unattended run as supervised is the failure that matters, and
    treating a supervised run as unattended only costs a refusal on a weak host.
    """
    return MODE_FLOORS[mode if mode is not None else ExecutionMode.AUTONOMOUS]


@dataclass(frozen=True)
class WorkloadPolicy:
    """What isolation a workload requires."""

    min_tier: IsolationTier
    network_allowed: bool = False
    max_memory_mb: int = 512
    max_timeout_s: int = 300
    reason: str = ""
    #: Who is watching. `None` is read as `AUTONOMOUS` — the stricter answer.
    mode: ExecutionMode | None = None
    #: Whether this workload runs code we did not write and cannot trust.
    #:
    #: The mode floor exists for adversarial code (ADR-093 decisions 1 and 6).
    #: Decision 3 is just as explicit the other way: "trusted first-party
    #: services keep container isolation ... microVM isolation is reserved for
    #: the *sandbox*". Applying the autonomous floor to a first-party Jira call
    #: would refuse it on every host without gVisor, which is not a security
    #: gain — it is the ADR being read past its own scope.
    untrusted: bool = True
    #: The egress this workload is granted. Default-deny (#77).
    egress: EgressGrant = DENY_ALL

    @property
    def effective_min_tier(self) -> IsolationTier:
        """The stricter of what the workload asked for and what its mode floors.

        Both, not either: a policy may need a stronger boundary than its mode
        requires, and a mode may require a stronger boundary than the policy
        thought to ask for. Taking one and ignoring the other is how an
        unattended run lands on Tier 3.
        """
        if not self.untrusted:
            return self.min_tier
        floor = floor_for_mode(self.mode)
        return self.min_tier if tier_satisfies(self.min_tier, floor) else floor


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
    untrusted=False,
    egress=EgressGrant(
        mode=EgressMode.HOST,
        reason="first-party tool calls a named external API; ADR-093 decision 3",
    ),
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
    untrusted=False,
    egress=EgressGrant(
        mode=EgressMode.HOST,
        reason="a browser without egress cannot browse; ADR-093 decision 3",
    ),
)

DEV_ONLY = WorkloadPolicy(
    min_tier="fake",
    network_allowed=True,
    reason="Development/test only — no real isolation",
    untrusted=False,
    egress=EgressGrant(mode=EgressMode.HOST, reason="dev/test only — no real isolation"),
)


def tier_satisfies(available: IsolationTier, required: IsolationTier) -> bool:
    """Does the available tier meet or exceed the required tier?"""
    avail_idx = _TIER_ORDER.index(available)
    req_idx = _TIER_ORDER.index(required)
    return avail_idx <= req_idx  # Lower index = stronger
