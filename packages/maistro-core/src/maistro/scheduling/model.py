"""Schedule as a definition filed in a Project.

A Schedule says *when* and *what to run*; it does not own an execution
concept. Firing produces a canonical Run from a GraphTemplate, so scheduled
work is the same durable, resumable, auditable object as interactive work —
one execution identity, one recovery model, one place to look when something
did not happen.

That is why there is no schedule-side execution table here: no `last_task_id`
binding recurrence to a parallel Task lifecycle, and no second job store with
its own misfire policy. `last_run_id` points into Run history, and "did we
miss a fire?" is answered from Runs in the scope.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from maistro.scheduling.cron import CronExpression, minimum_gap, parse_cron

__all__ = [
    "DEFAULT_CATCHUP_WINDOW_SECONDS",
    "OverlapPolicy",
    "PendingFire",
    "Schedule",
]

# How far back a restart will backfill missed fires. One hour keeps a deploy
# or crash from silently dropping the morning briefing, while refusing to
# stampede a year of missed fires after a long outage.
DEFAULT_CATCHUP_WINDOW_SECONDS: float = 3600.0


class OverlapPolicy(StrEnum):
    """What to do when a fire comes due while the previous Run is still going.

    Neither predecessor design specified this, and for agent work it is not an
    edge case: a twenty-minute research Run on a fifteen-minute schedule hits
    it every cycle.
    """

    SKIP = "skip"
    """Default. Drop the fire; the in-flight Run keeps going."""

    ALLOW = "allow"
    """Fire anyway; Runs proceed concurrently."""

    CANCEL_OTHER = "cancel_other"
    """Cancel the in-flight Run, then fire. For "latest wins" work."""

    BUFFER_ONE = "buffer_one"
    """Fire at most one queued occurrence after the current Run, dropping any
    others that came due in the meantime."""


class PendingFire(BaseModel):
    """A manual fire's held slot, durably, between reserve and settle (#1120).

    `ScheduleRunAdmitter._admit_manual` claims a schedule's run *before* the
    canonical Run exists, so two callers racing on the last `max_runs` unit
    cannot both take it. The claim used to advance `runs_so_far` (and disable
    on exhaustion) in that same write, which meant a process that died between
    the claim and the Run insert left the durable row showing a firing that
    never existed — on a `max_runs=1` schedule, one that bricked it: no Run,
    no retry possible, `enabled=False` forever (#1120: "failure before
    canonical Run creation does not advance/claim a firing that never
    existed").

    The marker is the reconciliation of that with the race safety: it holds
    the slot — every exhaustion check counts it — without spending it. The
    count, the disable, and `last_run_id` land in the one `settle_pending_fire`
    write that also removes the marker, so the durable row can only ever say
    "a run was spent" once a Run exists to spend it on. A holder that dies
    mid-window leaves the marker behind, and the next admission reconciles
    it against the Run store: a Run for its `fire_id` confirms the spend, no
    Run releases the slot. Freshness (`stamped_at`, wall-clock) is what lets
    recovery tell a dead holder from a live one still inside the window —
    see `admission._PENDING_FIRE_LEASE`.

    `updated_at_before` is for the trace-free release: a release nobody
    else has written over restores it, so a failed fire leaves the row
    byte-identical to what it was.
    """

    model_config = ConfigDict(extra="forbid")

    fire_id: str
    """The manual fire's occurrence token — the identity the Run will claim."""

    fires: int = 1
    """Slots this marker holds; one per manual fire."""

    stamped_at: datetime
    """Wall-clock instant the marker was written; drives lease staleness."""

    updated_at_before: datetime
    """The row's `updated_at` before the marker, restored on a clean release."""

    @model_validator(mode="after")
    def _normalise_timestamps(self) -> PendingFire:
        """Read naive wall-clock strings as UTC, exactly as `Schedule` does."""
        for field in ("stamped_at", "updated_at_before"):
            value = getattr(self, field)
            if value.tzinfo is None:
                object.__setattr__(self, field, value.replace(tzinfo=UTC))
        return self


def _now() -> datetime:
    return datetime.now(UTC)


class Schedule(BaseModel):
    """A recurrence rule plus the definition it instantiates."""

    model_config = ConfigDict(extra="forbid")

    schedule_id: str = Field(default_factory=lambda: uuid4().hex)
    workspace_id: str
    project_id: str
    name: str = ""

    cron: str
    timezone: str = "UTC"

    # What to run: a definition in the canonical layer, never a Task template.
    graph_template_id: str
    template_version: int | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)

    enabled: bool = True
    overlap_policy: OverlapPolicy = OverlapPolicy.SKIP
    catchup_window_seconds: float = DEFAULT_CATCHUP_WINDOW_SECONDS
    max_runs: int | None = None

    runs_so_far: int = 0
    last_fired_at: datetime | None = None
    last_run_id: str | None = None
    next_due_at: datetime | None = None
    recovered_occurrences: frozenset[datetime] = Field(default_factory=frozenset)
    """Pre-horizon occurrences (#1059) already credited toward `runs_so_far`.

    A durable per-occurrence signal, not a cursor: `last_fired_at` advances to
    the newest occurrence *this* evaluation consumed, whatever that batch is,
    so it can jump past a pre-horizon claim a lookup failed to see on the same
    tick — the cursor moving is then no proof the claim was ever counted
    (Codex review, #1533). Comparing a recovered claim against this set rather
    than against `last_fired_at` survives that: a rival ticker who *did* see
    the claim still credits it, whichever order the two writes land in.
    Bounded by `store._MAX_RECOVERED_OCCURRENCES` so a schedule that crashes
    over and over does not grow this set without limit.
    """

    pending_fires: tuple[PendingFire, ...] = ()
    """Manual-fire slots held but not yet spent (#1120) — see `PendingFire`.

    State, not definition: `ScheduleStore.put` keeps the stored value on a
    definition refresh, exactly as it keeps the cursors. Empty on an idle
    schedule; each entry exists only for the moments between a manual fire
    reserving its slot and the settle write that confirms or releases it.
    """

    persona_id: str | None = None
    actor_principal_id: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    @model_validator(mode="after")
    def _normalise_timestamps(self) -> Schedule:
        """Force every timestamp to be timezone-aware.

        The engine and stores compare these against an aware ``now``. A naive
        value used to validate cleanly and then raise `TypeError: can't
        compare offset-naive and offset-aware datetimes` deep inside
        `evaluate()` or `due()`, which takes the schedule out of service for a
        reason nothing on the creation path reported. A naive input is read as
        UTC, which is what a bare wall-clock string means here.
        """
        for field in ("last_fired_at", "next_due_at", "created_at", "updated_at"):
            value = getattr(self, field)
            if isinstance(value, datetime) and value.tzinfo is None:
                object.__setattr__(self, field, value.replace(tzinfo=UTC))
        return self

    @model_validator(mode="after")
    def _validate(self) -> Schedule:
        if not self.workspace_id.strip():
            raise ValueError("workspace_id must be a non-empty string")
        if not self.project_id.strip():
            raise ValueError("project_id must be a non-empty string")
        if not self.graph_template_id.strip():
            raise ValueError("graph_template_id must be a non-empty string")
        if self.catchup_window_seconds < 0:
            raise ValueError("catchup_window_seconds cannot be negative")
        if self.max_runs is not None and self.max_runs < 1:
            raise ValueError("max_runs must be at least 1 when set")
        if self.runs_so_far < 0:
            raise ValueError("runs_so_far cannot be negative")
        # Reject an unfireable schedule at creation, not at fire time.
        self.expression.next_fire(_now(), timezone=self.timezone)
        return self

    @property
    def expression(self) -> CronExpression:
        return parse_cron(self.cron)

    @property
    def exhausted(self) -> bool:
        """True when max_runs has been reached and the schedule is spent.

        Pending manual-fire markers count: a slot held between reserve and
        settle is not available, whether or not its Run has landed yet
        (#1120). The durable count alone would let the recurring evaluation
        spend a slot a live manual fire is mid-way through claiming.
        """
        if self.max_runs is None:
            return False
        held = sum(marker.fires for marker in self.pending_fires)
        return self.runs_so_far + held >= self.max_runs

    @property
    def runs_remaining(self) -> int | None:
        """Fires left before exhaustion, or None when unbounded.

        Counts held-but-unspent manual-fire markers (#1120) for the same
        reason `exhausted` does: a held slot is not a remaining one.
        """
        if self.max_runs is None:
            return None
        held = sum(marker.fires for marker in self.pending_fires)
        return max(0, self.max_runs - self.runs_so_far - held)

    def minimum_gap(self) -> timedelta:
        """Shortest interval this recurrence can produce.

        The substrate imposes no floor — how often is often enough is a
        product question — but a product enforces its own in one line:
        ``if schedule.minimum_gap() < timedelta(minutes=15): reject``.
        """
        return minimum_gap(self.cron, timezone=self.timezone)

    def next_fire_after(self, moment: datetime) -> datetime:
        """The next wall-clock fire strictly after ``moment``, in this
        schedule's timezone."""
        return self.expression.next_fire(moment, timezone=self.timezone)
