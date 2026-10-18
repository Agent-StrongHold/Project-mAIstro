"""The Goal reconciliation control loop (M3 #806).

Mechanics only: claim → derive facts from durable state → decide → admit
(fenced + idempotent) → sleep. What a decision *means* is #805's pluggable
:class:`ReconciliationPolicy`; the loop never invents a second scheduler or
execution queue — it records control metadata and lets the caller create the
canonical ``Goal -> Graph -> Run -> NodeRun -> Attempt`` work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

from maistro.goals.model import (
    Goal,
    GoalAdmission,
    GoalClaim,
    GoalFacts,
    GoalStatus,
    WakeFact,
    WakeReason,
    default_lease_ttl,
)
from maistro.goals.store import (
    GoalBudgetExhausted,
    GoalCancelled,
    GoalDeadlinePassed,
    GoalReconciliationError,
    GoalReconciliationStore,
    StaleGoalFence,
)

__all__ = [
    "GoalReconciler",
    "PhysicalAdmitter",
    "PlannedAdmission",
    "PolicyDecision",
    "ReconciliationOutcome",
    "ReconciliationPolicy",
]

DEFAULT_SWEEP_HORIZON = timedelta(seconds=60)
"""Bound on how long a Goal may sleep before the safety sweep re-derives its
state from durable facts. A missed wakeup is repaired within this horizon —
the sweep reads only Goals whose ``awake_after`` has passed, never every
Goal, and never continuously polls models."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class PlannedAdmission:
    """One piece of next work a policy wants admitted for a Goal.

    ``decision_key`` must be stable across replays of the same decision
    (e.g. derived from the triggering event's canonical id); it is the
    idempotency key that makes duplicate Event delivery and restart
    replays converge on one admission.
    """

    kind: str
    decision_key: str
    correlation_id: str = ""


@dataclass(frozen=True)
class PolicyDecision:
    """What a policy decided for one reconciliation pass."""

    admissions: tuple[PlannedAdmission, ...] = ()
    complete: bool = False
    blocked_reason: str | None = None
    sleep_for: timedelta | None = None


@runtime_checkable
class ReconciliationPolicy(Protocol):
    """The #805-owned decision semantics, plugged into these mechanics."""

    async def decide(self, facts: GoalFacts) -> PolicyDecision: ...


@runtime_checkable
class PhysicalAdmitter(Protocol):
    """Creates the canonical artifact an admission names (Run or Subgoal).

    Must be idempotent per ``GoalAdmission.decision_key``: crash points
    between recording the admission and creating the artifact are repaired
    by re-running this with the same admission, never by admitting twice.
    """

    async def admit(self, admission: GoalAdmission) -> str: ...


@dataclass
class ReconciliationOutcome:
    """One control-loop pass, inspectable as derived control metadata."""

    goal_id: str
    claimed: bool = False
    skipped_asleep: bool = False
    decided: bool = False
    admissions: list[GoalAdmission] = field(default_factory=list)
    duplicates: list[GoalAdmission] = field(default_factory=list)
    repaired: list[GoalAdmission] = field(default_factory=list)
    completed: bool = False
    slept_as: GoalStatus | None = None
    error: str | None = None


class GoalReconciler:
    """Event-driven, fenced, restart-safe reconciliation for canonical Goals.

    One instance per Workspace Agent (per ``holder`` identity). Several
    processes may run instances against one store: the durable claim picks
    at most one acting reconciler per Goal at a time, and the fence makes
    stale holders harmless.
    """

    def __init__(
        self,
        store: GoalReconciliationStore,
        policy: ReconciliationPolicy,
        *,
        holder: str,
        admitter: PhysicalAdmitter | None = None,
        lease_ttl: timedelta | None = None,
        sweep_horizon: timedelta = DEFAULT_SWEEP_HORIZON,
    ) -> None:
        self._store = store
        self._policy = policy
        self._holder = holder
        self._admitter = admitter
        self._lease_ttl = lease_ttl or default_lease_ttl()
        self._sweep_horizon = sweep_horizon

    # -- event-driven entry points ----------------------------------------

    async def wake(
        self,
        goal_id: str,
        *,
        reason: WakeReason,
        correlation_id: str = "",
        unblocks: bool = False,
        now: datetime | None = None,
    ) -> bool:
        """Record a durable wake fact. ``True`` if this is a new wake.

        Delivery of the canonical Event *records the fact*; reconciling it is
        a separate step, so a process that dies between the two is repaired
        by the sweep instead of losing the notification.
        """
        fact = await self._store.record_wake(
            goal_id,
            reason=reason,
            correlation_id=correlation_id,
            unblocks=unblocks,
            now=now,
        )
        return fact is not None

    async def reconcile(
        self, goal_id: str, *, now: datetime | None = None
    ) -> ReconciliationOutcome:
        """One claim → decide → admit → sleep pass for one Goal."""
        at = now or _utcnow()
        outcome = ReconciliationOutcome(goal_id=goal_id)
        claim = await self._store.claim(goal_id, holder=self._holder, ttl=self._lease_ttl, now=at)
        if claim is None:
            # Another reconciler owns this Goal right now; skip rather than
            # duplicate the work it is doing (the wake fact stays for the
            # safety sweep if its holder dies).
            return outcome
        outcome.claimed = True
        try:
            await self._pass(goal_id, claim, outcome, at)
        except StaleGoalFence as exc:
            outcome.error = f"stale fence: {exc}"
        except (GoalCancelled, GoalDeadlinePassed, GoalBudgetExhausted) as exc:
            outcome.error = str(exc)
            await self._sleep_blocked(goal_id, claim, str(exc), at)
        except GoalReconciliationError as exc:
            outcome.error = str(exc)
        finally:
            await self._store.release_claim(goal_id, fencing_token=claim.fencing_token)
        return outcome

    # -- bounded safety sweep / restart ------------------------------------

    async def sweep(
        self, now: datetime | None = None, *, limit: int = 16
    ) -> list[ReconciliationOutcome]:
        """Bounded repair pass: lapsed leases, missed wakes, due sleeps.

        Reads only indexed due rows bounded by ``limit`` — missed
        notifications are repaired without polling every Goal.
        """
        at = now or _utcnow()
        await self._store.reclaim_expired(at, limit)
        due = await self._store.due_goals(at, limit)
        outcomes: list[ReconciliationOutcome] = []
        for goal in due:
            outcomes.append(await self.reconcile(goal.goal_id, now=at))
        return outcomes

    async def recover(self, *, limit: int = 100) -> list[str]:
        """Restart reconstruction from durable canonical facts only.

        Returns the Goal ids the loop still owns. No process-local queue is
        involved: everything replays from the store (open admissions are
        repaired by the next reconcile/sweep of each Goal).
        """
        goals = await self._store.non_terminal_goals()
        return [goal.goal_id for goal in goals[:limit]]

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _asleep_with_no_relevant_change(goal: Goal, wakes: list[WakeFact], at: datetime) -> bool:
        """Whether a sleeping Goal must stay asleep for this pass.

        A sleeping Goal consumes no decisions until a relevant state change
        (an unblocking wake) or its bounded sweep horizon makes it due.
        """
        if goal.status not in GoalStatus.sleeping():
            return False
        if any(w.unblocks for w in wakes):
            return False
        return not (goal.awake_after is not None and goal.awake(at))

    async def _pass(
        self, goal_id: str, claim: GoalClaim, outcome: ReconciliationOutcome, at: datetime
    ) -> None:
        goal = await self._store.get_goal(goal_id)
        if goal is None:
            raise GoalReconciliationError(f"unknown Goal {goal_id!r}")
        if goal.status in GoalStatus.terminal():
            return

        wakes = await self._store.pending_wakes(goal_id)

        # Repair admissions recorded before a crash first: convergence of
        # already-admitted decisions is not "new work" and must not wait on
        # gates or sleeps.
        if self._admitter is not None:
            outcome.repaired.extend(await self._repair_open(goal_id, claim, at))

        if self._asleep_with_no_relevant_change(goal, wakes, at):
            outcome.skipped_asleep = True
            return
        if goal.deadline_passed(at):
            raise GoalDeadlinePassed(f"Goal {goal_id!r} deadline passed at {goal.deadline_at}")

        facts = GoalFacts(
            goal=goal,
            pending_wakes=tuple(wakes),
            pending_admissions=tuple(await self._store.pending_admissions(goal_id)),
            now=at,
        )
        decision = await self._policy.decide(facts)
        outcome.decided = True

        for planned in decision.admissions:
            admission, created = await self._store.admit(
                goal_id,
                fencing_token=claim.fencing_token,
                decision_key=planned.decision_key,
                kind=planned.kind,
                correlation_id=planned.correlation_id,
                now=at,
            )
            if not created:
                outcome.duplicates.append(admission)
                continue
            outcome.admissions.append(admission)
            if self._admitter is not None:
                physical_ref = await self._admitter.admit(admission)
                await self._store.complete_admission(
                    admission.admission_id, physical_ref=physical_ref, now=at
                )

        if decision.complete:
            await self._store.finish_goal(goal_id, fencing_token=claim.fencing_token, now=at)
            outcome.completed = True
        else:
            await self._sleep(goal_id, claim, decision, at, outcome)

        await self._store.mark_wakes_dispatched([w.wake_id for w in wakes], now=at)

    async def _repair_open(
        self, goal_id: str, claim: GoalClaim, at: datetime
    ) -> list[GoalAdmission]:
        """Finish admissions whose process died between record and artifact."""
        repaired: list[GoalAdmission] = []
        if self._admitter is None:
            return repaired
        for admission in await self._store.pending_admissions(goal_id):
            physical_ref = await self._admitter.admit(admission)
            await self._store.complete_admission(
                admission.admission_id, physical_ref=physical_ref, now=at
            )
            repaired.append(admission)
        return repaired

    async def _sleep(
        self,
        goal_id: str,
        claim: GoalClaim,
        decision: PolicyDecision,
        at: datetime,
        outcome: ReconciliationOutcome,
    ) -> None:
        status = GoalStatus.GATED if decision.blocked_reason else GoalStatus.DORMANT
        if decision.sleep_for is not None:
            awake_after: datetime | None = at + decision.sleep_for
        elif decision.blocked_reason:
            # Blocked (e.g. waiting on a human) sleeps until a relevant state
            # change wakes it — no bounded retry, so it consumes no decisions
            # (and no model calls) in the meantime.
            awake_after = None
        else:
            awake_after = at + self._sweep_horizon
        await self._store.sleep_goal(
            goal_id,
            status=status,
            fencing_token=claim.fencing_token,
            awake_after=awake_after,
            blocked_reason=decision.blocked_reason,
            now=at,
        )
        outcome.slept_as = status

    async def _sleep_blocked(
        self, goal_id: str, claim: GoalClaim, reason: str, at: datetime
    ) -> None:
        """Park a Goal after a gate refusal so it stops consuming decisions."""
        try:
            await self._store.sleep_goal(
                goal_id,
                status=GoalStatus.GATED,
                fencing_token=claim.fencing_token,
                awake_after=at + self._sweep_horizon,
                blocked_reason=reason,
                now=at,
            )
        except StaleGoalFence:
            # Claim already lost (e.g. cancel raced us); the cancelled state
            # is durable and fences admission on its own.
            return

    @property
    def holder(self) -> str:
        return self._holder
