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

    persona_id: str | None = None
    actor_principal_id: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

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
        """True when max_runs has been reached and the schedule is spent."""
        return self.max_runs is not None and self.runs_so_far >= self.max_runs

    @property
    def runs_remaining(self) -> int | None:
        """Fires left before exhaustion, or None when unbounded."""
        if self.max_runs is None:
            return None
        return max(0, self.max_runs - self.runs_so_far)

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
