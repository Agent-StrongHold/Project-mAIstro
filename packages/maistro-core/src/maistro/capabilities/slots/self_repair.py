"""self_repair slot types and protocol (SPEC-188).

The self_repair slot runs a bounded detect→diagnose→propose→act cycle. It owns
no host privilege: it reads via the infra_monitor slot and acts only via the
infra_action slot (which auto-runs safe tiers and routes risky ones through the
approval slot). These types are the unit of record for that loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from maistro.capabilities.protocols import CapabilityProvider
from maistro.capabilities.slots.infra import InfraHealth


class RepairDecision(StrEnum):
    """What the loop decided about a single proposal in one cycle."""

    ACTED = "acted"  # dispatched to infra_action and ran (safe tier)
    PENDING_APPROVAL = "pending_approval"  # dispatched; awaiting the approval slot
    SUPPRESSED = "suppressed"  # governor blocked it (budget/cooldown/flap/in-flight)
    PROPOSE_ONLY = "propose_only"  # diagnosable but never auto-acted (e.g. storage); escalated
    UNDIAGNOSED = "undiagnosed"  # degraded but no known remediation; escalated
    FAILED = "failed"  # dispatched and infra_action reported failure


@dataclass(frozen=True)
class RepairProposal:
    """A candidate remediation for one degraded resource.

    ``action`` is None for proposals that carry no actionable fix (propose-only
    or undiagnosed); ``tier`` is the SPEC-187 blast-radius tier when actionable,
    else "".
    """

    resource: str
    symptom: str
    action: str | None
    params: dict[str, Any] = field(default_factory=dict)
    tier: str = ""
    rationale: str = ""
    # True when the symptom is recognized by the rule table (even if no action is
    # taken, e.g. storage). False means undiagnosed — degraded but no known cause.
    recognized: bool = True


@dataclass(frozen=True)
class RepairResult:
    """A proposal plus the decision the loop reached for it this cycle."""

    proposal: RepairProposal
    decision: RepairDecision
    detail: str = ""


@dataclass(frozen=True)
class RepairCycleResult:
    """The outcome of one run_once() cycle — every proposal and its decision."""

    ts: str
    results: list[RepairResult] = field(default_factory=list)

    @property
    def acted(self) -> list[RepairResult]:
        return [r for r in self.results if r.decision is RepairDecision.ACTED]

    @property
    def escalated(self) -> list[RepairResult]:
        return [
            r
            for r in self.results
            if r.decision in {RepairDecision.PROPOSE_ONLY, RepairDecision.UNDIAGNOSED}
        ]


@runtime_checkable
class SelfRepair(CapabilityProvider, Protocol):
    """Detect→diagnose→propose→act remediation provider."""

    async def evaluate(self, health: InfraHealth) -> list[RepairProposal]:
        """Pure detect+diagnose+propose for a health snapshot (no side effects)."""
        ...

    async def run_once(self) -> RepairCycleResult:
        """One full cycle: snapshot → evaluate → govern → act."""
        ...
