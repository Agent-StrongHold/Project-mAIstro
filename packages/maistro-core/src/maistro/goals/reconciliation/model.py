"""Durable Goal and reconciliation control records (M3 #806).

Lives under ``maistro.goals.reconciliation`` because the control loop is
*about* a Goal, not because it redefines one: the canonical Goal ontology
(``maistro.goals``, #1572) owns ``goal_id`` / ``goal_revision`` and the
desired-state record. The reconciliation control records here (:class:`Goal`,
:class:`GoalClaim`, :class:`WakeFact`, :class:`GoalAdmission`) are *derived
control metadata* over that identity: they never redefine Goal lifecycle and
never carry Run/NodeRun/Attempt state — physical execution lineage stays in
the canonical Run store under ``Goal -> Graph -> Run -> NodeRun -> Attempt``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


class GoalStatus(StrEnum):
    """Reconciliation posture of a Goal — deliberately *not* an execution lifecycle.

    The vocabulary avoids Run/NodeRun/Attempt lifecycle words on purpose:
    ``Goal -> Graph -> Run -> NodeRun -> Attempt`` is the one execution
    identity (SPEC-177, check-execution-lifecycles), and this control-loop
    state must never read as a second one. A posture says whether the
    reconciler may claim and decide:

    - ``READY`` — the Goal may be claimed and decided now.
    - ``DORMANT`` — asleep until a relevant state change or the bounded
      safety sweep; consumes no decisions (and no model calls).
    - ``GATED`` — fenced off by a stop condition or an external gate (for
      example waiting on a human); sleeps until the gate resolves.
    - ``WITHDRAWN`` — stopped by policy or a person; fences admission
      across restarts.
    - ``SETTLED`` — the stop condition is satisfied; terminal.
    """

    READY = "ready"
    DORMANT = "dormant"
    GATED = "gated"
    WITHDRAWN = "withdrawn"
    SETTLED = "settled"

    @classmethod
    def sleeping(cls) -> tuple[GoalStatus, ...]:
        return (cls.DORMANT, cls.GATED)

    @classmethod
    def terminal(cls) -> tuple[GoalStatus, ...]:
        return (cls.WITHDRAWN, cls.SETTLED)


class Goal(BaseModel):
    """Canonical Goal record with reconciliation-relevant control fields."""

    goal_id: str
    workspace_id: str = ""
    project_id: str = ""
    owning_agent_id: str = ""
    revision: int = 1
    status: GoalStatus = GoalStatus.READY
    runs_admitted: int = 0
    budget_max_runs: int | None = None
    deadline_at: datetime | None = None
    stop_condition: str | None = None
    blocked_reason: str | None = None
    awake_after: datetime | None = None
    cancelled_reason: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    def budget_exhausted(self) -> bool:
        return self.budget_max_runs is not None and self.runs_admitted >= self.budget_max_runs

    def deadline_passed(self, now: datetime) -> bool:
        return self.deadline_at is not None and now >= self.deadline_at

    def awake(self, now: datetime) -> bool:
        """Whether the bounded safety sweep should consider this Goal due."""
        return self.awake_after is not None and now >= self.awake_after


class GoalClaim(BaseModel):
    """The one durable claim/lease/fence deciding which reconciler may act.

    Mirrors the generic leasing contract (ADR-081626-f383, ADR-082526-b36a):
    a monotonic ``fence_epoch`` plus an opaque ``fencing_token``. A holder
    must present the current token to admit work; losing or expiring the
    claim makes every earlier token stale, so a superseded reconciler cannot
    start a later Run even if its process keeps running.
    """

    goal_id: str
    holder: str
    fence_epoch: int
    fencing_token: str = Field(default_factory=lambda: uuid4().hex)
    acquired_at: datetime = Field(default_factory=_utcnow)
    expires_at: datetime | None = None

    def lapsed(self, now: datetime) -> bool:
        return self.expires_at is not None and now >= self.expires_at


class WakeReason(StrEnum):
    """Why the owning Workspace Agent should reconcile a Goal now."""

    GOAL_REVISION = "goal.revision"
    RUN_TERMINAL = "run.terminal"
    SUBGOAL_TRANSITION = "goal.subgoal.transition"
    HITL_RESOLVED = "goal.hitl.resolved"
    EVIDENCE_UPDATED = "goal.evidence.updated"
    SAFETY_SWEEP = "safety.sweep"
    MANUAL = "manual"


class WakeFact(BaseModel):
    """One durable wakeup fact for a Goal.

    ``wake_id`` is derived from the canonical correlation id (typically the
    ``event_id`` of the canonical Event that caused the change), so replayed
    or duplicated delivery of the same Event collapses to one wake fact.
    """

    wake_id: str
    goal_id: str
    reason: WakeReason
    correlation_id: str = ""
    unblocks: bool = False
    created_at: datetime = Field(default_factory=_utcnow)
    dispatched_at: datetime | None = None


class GoalAdmission(BaseModel):
    """A durable, idempotent record that a decision admitted next work.

    ``decision_key`` is the idempotency key: the same decision replayed after
    a duplicate Event or a restart resolves to the same admission row instead
    of a second admission. ``physical_ref`` names the canonical artifact the
    caller created (a ``run_id`` for a Run, a ``goal_id`` for a delegated
    Subgoal); reconciliation records the reference, it never *is* the
    execution.
    """

    admission_id: str = Field(default_factory=lambda: uuid4().hex)
    goal_id: str
    revision: int
    fence_epoch: int
    decision_key: str
    kind: str = "run"
    correlation_id: str = ""
    admitted_at: datetime = Field(default_factory=_utcnow)
    completed_at: datetime | None = None
    physical_ref: str | None = None


class GoalFacts(BaseModel):
    """Durable facts a policy sees when deciding. No process-local queue."""

    goal: Goal
    pending_wakes: tuple[WakeFact, ...] = ()
    pending_admissions: tuple[GoalAdmission, ...] = ()
    now: datetime = Field(default_factory=_utcnow)


def default_lease_ttl() -> timedelta:
    """Default claim TTL: two missed renewals lapse the lease (ADR-082526-b36a cadence guidance)."""
    return timedelta(seconds=30)


def wake_id_for(goal_id: str, correlation_id: str) -> str:
    """Deterministic wake id: same Goal + same canonical event = same fact."""
    return f"{goal_id}:{correlation_id}"


def coerce_datetime(value: Any) -> datetime:
    """Parse a stored datetime that may have been serialized as text."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
