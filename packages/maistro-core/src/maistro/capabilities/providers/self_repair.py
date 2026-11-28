"""RuleBasedRepair — the baseline self_repair provider (SPEC-188).

Runs the detect→diagnose→govern→act cycle. Owns no host privilege: it reads via
the infra_monitor slot and acts only via infra_action. Diagnosis is the
explicit rule table in ``self_repair_rules``; safety is the ``SafetyGovernor``.

Dispatch policy keeps run_once() non-blocking:
- auto-run actions (reversible under autonomy=auto_safe) are awaited inline → ACTED/FAILED;
- approval-gated actions admit a durable waiting-human NodeRun (#2405) →
  PENDING_APPROVAL. The cycle never blocks on an in-process ``asyncio.Event``.
The in-flight guard keeps a pending resource from being re-dispatched next cycle.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal

from maistro.capabilities.self_repair_governor import SafetyGovernor
from maistro.capabilities.self_repair_incident import stable_effect_key
from maistro.capabilities.self_repair_rules import diagnose
from maistro.capabilities.slots.infra import (
    ActionResult,
    ActionTier,
    InfraHealth,
    InfraMonitor,
    tier_for,
)
from maistro.capabilities.slots.self_repair import (
    RepairCycleResult,
    RepairDecision,
    RepairProposal,
    RepairResult,
)
from maistro.capabilities.types import ProviderHealth

logger = logging.getLogger("maistro.capabilities.self_repair")

Autonomy = Literal["approve_all", "auto_safe", "detect_only"]


InfraEffectInvoker = Callable[[str, dict[str, Any], str], Awaitable[ActionResult]]
#: Admit one approval-gated proposal as a durable waiting-human Run; return its run_id.
ApprovalAdmittor = Callable[[RepairProposal, str], Awaitable[str]]
#: Look up a parked approval Run's status value (e.g. ``cancelled``); ``None`` if unknown.
ApprovalRunStatus = Callable[[str], Awaitable[str | None]]
#: Durable index of pending approval waits (resource -> run_id), read fresh at
#: each cycle so a restart or a second replica reconciles waits it did not
#: admit itself (#2405). An empty mapping is a normal answer, not an error.
PendingApprovalsLoader = Callable[[], Awaitable[Mapping[str, str]]]

#: Durable Run statuses that settle an approval wait and release the governor.
_TERMINAL_APPROVAL_STATUSES = frozenset({"completed", "failed", "cancelled", "timed_out"})


class RuleBasedRepair:
    """Baseline self_repair provider — rule-table diagnosis + safety governor.

    Production wiring supplies an Invocation-backed invoker and a durable
    approval admittor. The actor retains no infra_action provider and cannot
    dispatch an effect outside those seams.
    """

    def __init__(
        self,
        *,
        infra_monitor: InfraMonitor | None,
        effect_invoker: InfraEffectInvoker | None = None,
        approval_admittor: ApprovalAdmittor | None = None,
        approval_run_status: ApprovalRunStatus | None = None,
        pending_approvals_loader: PendingApprovalsLoader | None = None,
        governor: SafetyGovernor | None = None,
        autonomy: Autonomy = "auto_safe",
        max_actions_per_cycle: int = 2,
    ) -> None:
        self._monitor = infra_monitor
        self._effect_invoker = effect_invoker
        self._approval_admittor = approval_admittor
        self._approval_run_status = approval_run_status
        self._pending_approvals_loader = pending_approvals_loader
        self._governor = governor or SafetyGovernor()
        self._autonomy = autonomy
        self._max_actions = max_actions_per_cycle
        self._last_cycle: RepairCycleResult | None = None
        #: run_ids parked for approval this process (presentation; truth is the store).
        self._pending_approval_runs: dict[str, str] = {}

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

        # Release in_flight for waits that settled out-of-band (cancel_hitl,
        # timeout, resume-to-completion) so later faults on that resource are
        # not permanently suppressed (#2405 Codex P2), and reconcile waits this
        # process never admitted (a restart or a second replica) before the
        # degraded snapshot can admit a duplicate (#2405 restart audit). A
        # failed hydration refuses the cycle: without durable evidence of what
        # is already parked, admitting anything would guess.
        if not await self._reconcile_pending_approvals():
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

    async def _reconcile_pending_approvals(self) -> bool:
        """Hydrate durable pending waits, then release settled ones.

        Returns False when the cycle must be refused (hydration failed): a
        process that cannot see durable pending waits must not admit new work
        on top of that blindness. Hydration runs whenever the process-local
        pending dict is empty — a fresh process, a restart, or a second
        replica's first cycle — and restores the governor's in-flight guard
        from durable truth, not local bookkeeping.
        """
        if not await self._hydrate_pending_approvals():
            return False
        await self._release_settled_approvals()
        return True

    async def _hydrate_pending_approvals(self) -> bool:
        """Restore the in-flight guard from the durable HITL-paused scan.

        False means the durable surface exists but failed: admitting over
        that blindness would guess, so the caller refuses the cycle.
        """
        if self._pending_approvals_loader is None or self._pending_approval_runs:
            return True
        try:
            hydrated = await self._pending_approvals_loader()
        except Exception as exc:
            logger.warning("self_repair: pending approval hydration failed: %s", exc)
            return False
        for resource, run_id in hydrated.items():
            if resource in self._pending_approval_runs:
                continue
            self._pending_approval_runs[resource] = run_id
            # Restore the in-flight guard without consuming budget or
            # cooldown bookkeeping: the wait was dispatched (possibly by
            # another process), and the governor must hold the resource
            # until the Run settles. Cooldowns and budgets still gate any
            # *new* dispatch — hydration removes neither.
            self._governor.mark_in_flight(resource)
        return True

    async def _release_settled_approvals(self) -> None:
        """Release in-flight resources whose approval Run settled terminally."""
        if not self._pending_approval_runs or self._approval_run_status is None:
            return
        settled: list[str] = []
        for resource, run_id in self._pending_approval_runs.items():
            status = await self._pending_run_status(resource, run_id)
            if status is None or status not in _TERMINAL_APPROVAL_STATUSES:
                continue
            self._governor.record_result(resource, recovered=(status == "completed"))
            settled.append(resource)
        for resource in settled:
            del self._pending_approval_runs[resource]

    async def _pending_run_status(self, resource: str, run_id: str) -> str | None:
        """One wait's durable status; None on lookup failure (never settles)."""
        status_of = self._approval_run_status
        if status_of is None:
            return None
        try:
            return await status_of(run_id)
        except Exception as exc:
            logger.warning(
                "self_repair: approval run status lookup failed for %s (%s): %s",
                resource,
                run_id,
                exc,
            )
            return None

    # --- per-proposal handling ---
    async def _handle(self, proposal: RepairProposal, dispatched: int) -> tuple[RepairResult, bool]:
        if not proposal.recognized:
            return RepairResult(proposal, RepairDecision.UNDIAGNOSED, "no known remediation"), False
        if proposal.action is None:
            return RepairResult(
                proposal, RepairDecision.PROPOSE_ONLY, "escalated for human review"
            ), False
        if self._autonomy == "detect_only" or self._effect_invoker is None:
            detail = (
                "autonomy=detect_only"
                if self._autonomy == "detect_only"
                else "no governed infra_action"
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
            return await self._admit_approval(proposal), True
        return await self._auto_run(proposal), True

    def _will_gate_on_approval(self, proposal: RepairProposal) -> bool:
        tier = tier_for(proposal.action or "", proposal.params)
        return tier is ActionTier.DESTRUCTIVE or (
            tier is ActionTier.REVERSIBLE and self._autonomy != "auto_safe"
        )

    async def _admit_approval(self, proposal: RepairProposal) -> RepairResult:
        """Park the action on a durable waiting-human NodeRun (#2405).

        Never awaits an in-process approval Event. Without an admittor the
        proposal is suppressed rather than spawning a process-local waiter.
        The effect key is derived from durable facts (workspace-independent
        resource/action/request digest), not ``id(proposal)``: a restart or a
        second replica observing the same incident computes the same key, so
        the canonical claim in the admittor converges on one Run.
        """
        action = proposal.action or ""
        effect_key = stable_effect_key(proposal.resource, action, proposal.params)
        if self._approval_admittor is None:
            self._governor.record_result(proposal.resource, recovered=False)
            return RepairResult(
                proposal,
                RepairDecision.SUPPRESSED,
                "no durable approval admittor; refusing in-process InboxApproval wait",
            )
        try:
            run_id = await self._approval_admittor(proposal, effect_key)
        except Exception as exc:
            logger.warning(
                "self_repair: durable approval admission failed for %s: %s",
                proposal.resource,
                exc,
            )
            self._governor.record_result(proposal.resource, recovered=False)
            return RepairResult(proposal, RepairDecision.FAILED, str(exc))
        self._pending_approval_runs[proposal.resource] = run_id
        return RepairResult(
            proposal,
            RepairDecision.PENDING_APPROVAL,
            f"awaiting approval run_id={run_id}",
        )

    async def _auto_run(self, proposal: RepairProposal) -> RepairResult:
        recovered = False
        decision = RepairDecision.FAILED
        detail = ""
        try:
            result = await self._invoke_action(proposal)
            recovered = bool(result.ok)
            decision = RepairDecision.ACTED if recovered else RepairDecision.FAILED
            detail = result.detail or ("dispatched" if recovered else "action failed")
        except Exception as exc:
            detail = str(exc)
        self._governor.record_result(proposal.resource, recovered=recovered)
        return RepairResult(proposal, decision, detail)

    async def _invoke_action(self, proposal: RepairProposal) -> ActionResult:
        """Admit one action through the canonical effect boundary."""
        if self._effect_invoker is None:
            return ActionResult(ok=False, detail="no governed infra_action")
        action = proposal.action or ""
        return await self._effect_invoker(
            action,
            proposal.params,
            stable_effect_key(proposal.resource, action, proposal.params),
        )
