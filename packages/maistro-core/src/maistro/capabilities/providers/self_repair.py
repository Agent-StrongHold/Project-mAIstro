"""RuleBasedRepair — the baseline self_repair provider (SPEC-188).

Runs the detect→diagnose→govern→act cycle. Owns no host privilege: it reads via
the infra_monitor slot and acts only via infra_action (which itself auto-runs
safe tiers and routes risky ones through the approval slot). Diagnosis is the
explicit rule table in ``self_repair_rules``; safety is the ``SafetyGovernor``.

Dispatch policy keeps run_once() non-blocking:
- auto-run actions (reversible under autonomy=auto_safe) are awaited inline → ACTED/FAILED;
- approval-gated actions (destructive, or reversible when not auto_safe) are launched
  as tracked background tasks → PENDING_APPROVAL (the cycle never blocks on a human).
The in-flight guard keeps a pending resource from being re-dispatched next cycle.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Literal

from maistro.capabilities.self_repair_governor import SafetyGovernor
from maistro.capabilities.self_repair_rules import diagnose
from maistro.capabilities.slots.infra import ActionTier, tier_for
from maistro.capabilities.slots.self_repair import (
    RepairCycleResult,
    RepairDecision,
    RepairProposal,
    RepairResult,
)
from maistro.capabilities.types import ProviderHealth

if TYPE_CHECKING:
    from maistro.capabilities.slots.infra import InfraAction, InfraHealth, InfraMonitor

logger = logging.getLogger("maistro.capabilities.self_repair")

Autonomy = Literal["approve_all", "auto_safe", "detect_only"]


class RuleBasedRepair:
    """Baseline self_repair provider — rule-table diagnosis + safety governor."""

    def __init__(
        self,
        *,
        infra_monitor: InfraMonitor | None,
        infra_action: InfraAction | None,
        governor: SafetyGovernor | None = None,
        autonomy: Autonomy = "auto_safe",
        max_actions_per_cycle: int = 2,
    ) -> None:
        self._monitor = infra_monitor
        self._action = infra_action
        self._governor = governor or SafetyGovernor()
        self._autonomy = autonomy
        self._max_actions = max_actions_per_cycle
        self._tasks: set[asyncio.Task[Any]] = set()
        self._last_cycle: RepairCycleResult | None = None

    # --- CapabilityProvider ---
    @property
    def name(self) -> str:
        return "rule_based_repair"

    @property
    def slot(self) -> str:
        return "self_repair"

    @property
    def trust_tier(self) -> str:
        return "t0"

    def requires(self) -> tuple[str, ...]:
        return ()

    async def healthcheck(self) -> ProviderHealth:
        if self._monitor is None:
            return ProviderHealth(healthy=False, detail="no infra_monitor wired")
        return ProviderHealth(healthy=True)

    # --- introspection for the API/UI ---
    @property
    def last_cycle(self) -> RepairCycleResult | None:
        return self._last_cycle

    def governor_state(self) -> dict[str, dict[str, object]]:
        return self._governor.state_summary()

    # --- SelfRepair ---
    async def evaluate(self, health: InfraHealth) -> list[RepairProposal]:
        # Pure detect+diagnose; an LLM explanation step (advisory-only) could attach
        # rationale here in a future provider without changing the action/tier.
        return diagnose(health)

    async def run_once(self) -> RepairCycleResult:
        if self._monitor is None:
            self._last_cycle = RepairCycleResult(ts="", results=[])
            return self._last_cycle

        try:
            health = await self._monitor.snapshot()
        except Exception as exc:  # monitor failure → safe_noop empty cycle, never raise
            logger.warning("self_repair: infra_monitor.snapshot failed: %s", exc)
            self._last_cycle = RepairCycleResult(ts="", results=[])
            return self._last_cycle

        proposals = await self.evaluate(health)
        results: list[RepairResult] = []
        dispatched = 0

        for proposal in proposals:
            result, did_dispatch = await self._handle(proposal, dispatched)
            results.append(result)
            dispatched += int(did_dispatch)

        self._last_cycle = RepairCycleResult(ts=health.ts, results=results)
        return self._last_cycle

    # --- per-proposal handling ---
    async def _handle(self, proposal: RepairProposal, dispatched: int) -> tuple[RepairResult, bool]:
        if not proposal.recognized:
            return RepairResult(proposal, RepairDecision.UNDIAGNOSED, "no known remediation"), False
        if proposal.action is None:
            return RepairResult(
                proposal, RepairDecision.PROPOSE_ONLY, "escalated for human review"
            ), False
        if self._autonomy == "detect_only" or self._action is None:
            detail = (
                "autonomy=detect_only" if self._autonomy == "detect_only" else "no infra_action"
            )
            return RepairResult(proposal, RepairDecision.SUPPRESSED, detail), False
        if dispatched >= self._max_actions:
            return RepairResult(
                proposal, RepairDecision.SUPPRESSED, "per-cycle action cap reached"
            ), False

        decision = self._governor.allow(proposal.resource)
        if not decision.allowed:
            return RepairResult(proposal, RepairDecision.SUPPRESSED, decision.reason.value), False

        self._governor.record_dispatch(proposal.resource)
        if self._will_gate_on_approval(proposal):
            # Don't block the cycle on a human — dispatch and track.
            self._dispatch_async(proposal)
            return RepairResult(
                proposal, RepairDecision.PENDING_APPROVAL, "awaiting approval"
            ), True
        return await self._auto_run(proposal), True

    def _will_gate_on_approval(self, proposal: RepairProposal) -> bool:
        tier = tier_for(proposal.action or "", proposal.params)
        return tier is ActionTier.DESTRUCTIVE or (
            tier is ActionTier.REVERSIBLE and self._autonomy != "auto_safe"
        )

    async def _auto_run(self, proposal: RepairProposal) -> RepairResult:
        recovered = False
        decision = RepairDecision.FAILED
        detail = ""
        try:
            result = await self._action.act(proposal.action or "", proposal.params)  # type: ignore[union-attr]
            recovered = bool(result.ok)
            decision = RepairDecision.ACTED if recovered else RepairDecision.FAILED
            detail = result.detail or ("dispatched" if recovered else "action failed")
        except Exception as exc:
            detail = str(exc)
        self._governor.record_result(proposal.resource, recovered=recovered)
        return RepairResult(proposal, decision, detail)

    def _dispatch_async(self, proposal: RepairProposal) -> None:
        action = proposal.action or ""
        params = proposal.params
        resource = proposal.resource

        async def _run() -> None:
            recovered = False
            try:
                result = await self._action.act(action, params)  # type: ignore[union-attr]
                recovered = bool(result.ok)
            except Exception as exc:
                logger.warning("self_repair: action %s on %s failed: %s", action, resource, exc)
            finally:
                self._governor.record_result(resource, recovered=recovered)

        task = asyncio.ensure_future(_run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
