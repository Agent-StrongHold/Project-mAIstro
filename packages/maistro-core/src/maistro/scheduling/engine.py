"""Pure fire decisions for a Schedule.

Everything about *whether and when* a schedule fires lives here, as a
function of (schedule, now, whether a prior Run is active). No clock, no
store, no I/O — so the semantics that actually bite in production (missed
fires after a restart, an overrunning Run, a bounded recurrence reaching its
last fire) are exhaustively testable instead of being emergent behaviour of a
polling loop.

The caller does the effects: create the Run, cancel the prior Run when asked,
persist the new cursor.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

from maistro.scheduling.model import (
    MAX_CATCHUP_WINDOW_SECONDS,
    OverlapPolicy,
    Schedule,
)

__all__ = [
    "DEFAULT_ENUMERATION_LIMITS",
    "EnumerationLimits",
    "FireDecision",
    "ScheduleEvaluation",
    "SkipReason",
    "SkippedFire",
    "evaluate",
]

# How many occurrences one evaluation will carry. The catchup window is the
# real bound — at one-minute granularity a one-hour window holds 60 and a
# one-day window 1440 — and this caps what a single decision returns.
_DEFAULT_MAX_ENUMERATED_FIRES: Final = 512

# One evaluation's catch-up walk reads the wall clock this often (in steps) to
# check its time budget. The check costs a monotonic-clock read, so it runs at
# a fixed stride rather than per step; at cron's one-minute granularity the
# stride keeps the clock overhead below 0.5% of the walk while bounding how
# far past the deadline any single step can overrun it.
_CLOCK_CHECK_STRIDE: Final = 256


def _default_walk_steps(max_window_seconds: float) -> int:
    """The occurrence bound derived from the window bound (#1200).

    Not an independent magic number: cron's finest cadence is one fire per
    minute, so a walk over a window of W seconds can never produce more than
    W/60 occurrences, plus one tick-interval's worth of slack past the window
    edge (the walk resumes from `last_fired_at`, which can sit just before the
    horizon). Under the substrate's seven-day window cap this is 10,080 + 64 =
    10,144 steps — the entire possible backlog — so the bound is a backstop
    that only a host overriding the window cap beyond it can reach. The old
    flat 50,000-step constant was the same idea unexplained and underived;
    replacing it with this derivation is what makes the walk's cost a stated
    property of the window contract instead of an accident of a constant.
    """
    return math.ceil(max_window_seconds / 60) + 64


@dataclass(frozen=True)
class EnumerationLimits:
    """Host-selected bounds on one evaluation's catch-up work (#1200).

    The audit this answers measured one evaluation of a stale per-minute
    schedule taking ~0.64s of synchronous event-loop time — 50,000 cron
    reparses — long enough to stall unrelated work sharing the loop. The
    bounds below close that along all three axes the work can grow on:

    - **window** — at most ``max_window_seconds`` of backlog is considered,
      whatever the schedule's own ``catchup_window_seconds`` says (which the
      definition model separately caps at
      ``model.MAX_CATCHUP_WINDOW_SECONDS``; this is the evaluation-time
      backstop for a host that raises that cap);
    - **occurrences** — the walk stops after ``max_walk_steps`` steps (the
      default derives from the window bound — see `_default_walk_steps`);
    - **time** — the walk stops after ``walk_budget_seconds`` of wall clock.

    Stopping early is reported, never silent: the evaluation carries
    ``enumeration_incomplete`` (and where it stopped), and admission treats an
    incomplete walk like a buffered occurrence — the due cursor stays put so
    the next tick re-examines exactly the range this one did not. Hosts that
    need the whole window walked in one evaluation may raise the budget (a
    batch context might pass ``math.inf``); a host on a latency-critical loop
    may lower it, or run ``evaluate`` on a worker thread — it is a pure
    function of its arguments and safe to offload.
    """

    max_window_seconds: float = MAX_CATCHUP_WINDOW_SECONDS
    max_walk_steps: int | None = None
    """None derives the bound from ``max_window_seconds`` (see
    ``_default_walk_steps``)."""
    walk_budget_seconds: float = 0.1
    max_enumerated_fires: int = _DEFAULT_MAX_ENUMERATED_FIRES

    def __post_init__(self) -> None:
        if self.max_window_seconds <= 0:
            raise ValueError("max_window_seconds must be positive")
        if self.max_walk_steps is not None and self.max_walk_steps < 1:
            raise ValueError("max_walk_steps must be at least 1 when set")
        if self.walk_budget_seconds < 0:
            raise ValueError("walk_budget_seconds cannot be negative")
        if self.max_enumerated_fires < 1:
            raise ValueError("max_enumerated_fires must be at least 1")

    @property
    def walk_steps(self) -> int:
        return (
            self.max_walk_steps
            if self.max_walk_steps is not None
            else _default_walk_steps(self.max_window_seconds)
        )


DEFAULT_ENUMERATION_LIMITS = EnumerationLimits()


class SkipReason(StrEnum):
    """Why an occurrence that came due did not produce a Run."""

    BUFFERED = "buffered"
    """Held back under BUFFER_ONE while a Run is active. The cursor does not
    advance, so it becomes due again on the next evaluation — which is what
    "run one queued occurrence afterwards" means to a polling caller."""

    DISABLED = "disabled"
    EXHAUSTED = "exhausted"
    OUTSIDE_CATCHUP = "outside_catchup"
    OVERLAP = "overlap"

    TRUNCATED = "truncated"
    """Beyond the per-evaluation enumeration cap. Reported rather than dropped
    silently, since a caller that advances its cursor on this decision would
    otherwise lose the occurrence with no record of it."""


@dataclass(frozen=True)
class FireDecision:
    """One occurrence that should become a Run."""

    scheduled_for: datetime
    """The nominal fire time, not the moment the tick noticed it. This is what
    the Run records, so a Run that started late is still attributable to the
    occurrence it belongs to."""

    catchup: bool = False
    """True when this occurrence came due while nothing was evaluating it —
    a backfill after downtime rather than a fire on time."""


@dataclass(frozen=True)
class SkippedFire:
    """An occurrence that came due and was deliberately not run."""

    scheduled_for: datetime
    reason: SkipReason


@dataclass(frozen=True)
class ScheduleEvaluation:
    """The complete decision for one evaluation of one schedule."""

    fires: tuple[FireDecision, ...] = ()
    skipped: tuple[SkippedFire, ...] = ()
    next_due_at: datetime | None = None
    cancel_active_run: bool = False
    """CANCEL_OTHER asked for the in-flight Run to be cancelled before firing."""
    exhausted: bool = False
    """max_runs is reached once these fires are recorded; disable the schedule."""
    enumeration_incomplete: bool = False
    """The catch-up walk stopped before reaching `now` (#1200).

    The occurrences between where it stopped and `now` were never considered —
    they are neither fired nor skipped, and claiming otherwise would be the
    dishonest semantics this field exists to prevent. Admission responds by
    leaving the due cursor where it is, so the next evaluation re-examines
    exactly the range this one did not; nothing is lost and nothing is
    pretended to have been considered. ``enumeration_stopped_at`` says where
    the walk got to.
    """
    enumeration_stopped_at: datetime | None = None
    """The exclusive end of what the walk examined when incomplete; None means
    it walked through `now` and examined everything in the window."""
    window_clamped: bool = False
    """The host's window bound (``EnumerationLimits.max_window_seconds``) is
    smaller than this schedule's own ``catchup_window_seconds``, so the
    evaluation considered the clamped window. Occurrences older than the
    effective horizon sit behind ``enumeration_start`` exactly as for a
    schedule whose own window is smaller — not enumerated, rather than
    enumerated and skipped — but an operator reading the skips should know
    the schedule's configured window was not the one applied."""


def _enumerate_due(
    schedule: Schedule,
    *,
    since: datetime,
    now: datetime,
    limits: EnumerationLimits,
) -> tuple[list[datetime], list[datetime], bool, datetime | None]:
    """Occurrences in (since, now], oldest first, plus any dropped by the caps.

    Three bounds close the walk (#1200), all host-selected via
    ``EnumerationLimits``: the window (already applied by the caller through
    `since`), the number of steps, and the wall-clock budget. When the step or
    budget bound stops the walk before it reaches `now`, the second element is
    the truncated tail as usual, the third is True, and the fourth is the
    exclusive end of what was actually examined. The unexamined range is
    deliberately *not* reported as skipped occurrences: it was never
    enumerated, so pretending to know which occurrences it held would be
    exactly the dishonest semantics the incompleteness flag exists to avoid.

    When more occurrences are due than one evaluation will carry, the *newest*
    are kept: they are the ones a caller still wants to act on. The older
    remainder is returned separately so it can be reported rather than
    vanishing.
    """
    occurrences: list[datetime] = []
    cursor = since
    started = time.monotonic()
    deadline = started + limits.walk_budget_seconds
    steps = 0
    stopped_at: datetime | None = None
    while True:
        # Checked on stride — and before the first step, so a zero budget
        # stops before doing any work at all rather than after 256 steps.
        # ``>=`` is what makes a zero budget deterministic: the deadline is
        # ``started`` itself and the second read is never behind it.
        if (steps % _CLOCK_CHECK_STRIDE == 0 or not occurrences) and time.monotonic() >= deadline:
            stopped_at = cursor
            break
        cursor = schedule.next_fire_after(cursor)
        steps += 1
        if cursor > now:
            break
        occurrences.append(cursor)
        if len(occurrences) >= limits.walk_steps:
            # Only reachable when the host's step bound is tighter than its
            # window implies (the default derives the step bound from the
            # window, so the whole window fits); stop rather than walk on.
            # The walk did not reach `now`, so this is incompleteness, not
            # merely truncation of what was seen.
            if cursor < now:
                stopped_at = cursor
            break
    if len(occurrences) <= limits.max_enumerated_fires:
        return occurrences, [], stopped_at is not None, stopped_at
    split = len(occurrences) - limits.max_enumerated_fires
    return (
        occurrences[split:],
        occurrences[:split],
        stopped_at is not None,
        stopped_at,
    )


def _catchup_horizon(schedule: Schedule, *, now: datetime, limits: EnumerationLimits) -> datetime:
    window = schedule.catchup_window_seconds
    if window > limits.max_window_seconds:
        window = limits.max_window_seconds
    return now - timedelta(seconds=window)


def _partition_by_catchup(
    occurrences: list[datetime], *, horizon: datetime
) -> tuple[list[datetime], list[SkippedFire]]:
    """Split occurrences into those still worth running and those too old.

    An occurrence older than the catchup window is dropped on purpose: after a
    long outage, replaying every missed fire is a stampede, not a recovery.
    """
    eligible = [moment for moment in occurrences if moment >= horizon]
    stale = [
        SkippedFire(scheduled_for=moment, reason=SkipReason.OUTSIDE_CATCHUP)
        for moment in occurrences
        if moment < horizon
    ]
    return eligible, stale


def _held(occurrences: list[datetime]) -> list[SkippedFire]:
    return [SkippedFire(scheduled_for=moment, reason=SkipReason.BUFFERED) for moment in occurrences]


def _overlapped(occurrences: list[datetime]) -> list[SkippedFire]:
    return [SkippedFire(scheduled_for=moment, reason=SkipReason.OVERLAP) for moment in occurrences]


def _apply_overlap(
    eligible: list[datetime],
    *,
    policy: OverlapPolicy,
    active_run: bool,
) -> tuple[list[datetime], list[SkippedFire], bool]:
    """Resolve overlap, returning (to_fire, skipped, cancel_active_run)."""
    if policy is OverlapPolicy.ALLOW:
        return eligible, [], False

    if policy is OverlapPolicy.CANCEL_OTHER:
        # Only the newest occurrence matters when the rule is "latest wins".
        newest = eligible[-1:]
        return newest, _overlapped(eligible[:-1]), active_run and bool(newest)

    if policy is OverlapPolicy.BUFFER_ONE:
        # Buffering is not concurrency. At most one occurrence may be waiting,
        # and it does not run until the active Run finishes: it is held with
        # its cursor un-advanced, so it comes due again on the next
        # evaluation. Everything older than the held one is dropped, which is
        # the "at most one queued" half of the policy.
        runnable = [] if active_run else eligible[:1]
        waiting = eligible[len(runnable) :]
        return (
            runnable,
            _overlapped(waiting[:-1]) + _held(waiting[-1:]),
            False,
        )

    if active_run:
        return [], _overlapped(eligible), False

    # Nothing running: the first occurrence fires and itself becomes the
    # in-flight Run, so later occurrences in the same batch overlap it.
    return eligible[:1], _overlapped(eligible[1:]), False


def _apply_max_runs(
    to_fire: list[datetime], *, remaining: int | None
) -> tuple[list[datetime], list[SkippedFire]]:
    if remaining is None:
        return to_fire, []
    allowed, refused = to_fire[:remaining], to_fire[remaining:]
    return allowed, [
        SkippedFire(scheduled_for=moment, reason=SkipReason.EXHAUSTED) for moment in refused
    ]


def enumeration_start(
    schedule: Schedule,
    *,
    now: datetime,
    limits: EnumerationLimits = DEFAULT_ENUMERATION_LIMITS,
) -> datetime:
    """The exclusive lower bound of what `evaluate` enumerates at `now`.

    Three lower bounds, all of them real: the catchup window (which bounds
    both the semantics and the size of the walk), the last fire, and the moment
    the schedule came into existence — creating a schedule must not
    retroactively schedule work from before it existed. The window considered
    is the tighter of the schedule's own and the host's bound (#1200), the
    same clamp `evaluate` applies, so a caller walking recovery against this
    start examines exactly the range an evaluation would. Public so the
    admitter can tell which occurrences an evaluation will *not* look at
    (#1059): a winner whose ticker died before the horizon passed is never
    enumerated, and the admitter's recovery walk has to stop exactly where
    this starts.
    """
    horizon = _catchup_horizon(schedule, now=now, limits=limits)
    return max(schedule.last_fired_at or horizon, horizon, schedule.created_at)


def evaluate(
    schedule: Schedule,
    *,
    now: datetime,
    active_run: bool = False,
    limits: EnumerationLimits = DEFAULT_ENUMERATION_LIMITS,
) -> ScheduleEvaluation:
    """Decide what a schedule should do at ``now``.

    ``active_run`` is whether a Run this schedule started is still in flight;
    the caller answers that from Run state, which is the only place it lives.

    ``limits`` are the host's bounds on this evaluation's catch-up work
    (#1200): the window considered, the number of occurrences walked, and the
    wall-clock budget for the walk. Reaching the budget or step bound marks
    the evaluation ``enumeration_incomplete`` rather than pretending the
    unexamined range was considered; admission then keeps the due cursor so
    the next tick re-examines it.
    """
    if not schedule.enabled:
        return ScheduleEvaluation(next_due_at=None)
    if schedule.exhausted:
        return ScheduleEvaluation(next_due_at=None, exhausted=True)

    horizon = _catchup_horizon(schedule, now=now, limits=limits)
    window_clamped = schedule.catchup_window_seconds > limits.max_window_seconds
    since = enumeration_start(schedule, now=now, limits=limits)
    occurrences, truncated, incomplete, stopped_at = _enumerate_due(
        schedule, since=since, now=now, limits=limits
    )
    eligible, stale = _partition_by_catchup(occurrences, horizon=horizon)

    to_fire, overlapped, cancel_active = _apply_overlap(
        eligible,
        policy=schedule.overlap_policy,
        active_run=active_run,
    )
    allowed, refused = _apply_max_runs(to_fire, remaining=schedule.runs_remaining)

    fires = tuple(
        FireDecision(scheduled_for=moment, catchup=moment < _fresh_boundary(now))
        for moment in allowed
    )
    remaining_after = schedule.runs_remaining
    exhausted = remaining_after is not None and len(allowed) >= remaining_after
    dropped = [
        SkippedFire(scheduled_for=moment, reason=SkipReason.TRUNCATED) for moment in truncated
    ]
    return ScheduleEvaluation(
        fires=fires,
        skipped=tuple(dropped + stale + overlapped + refused),
        next_due_at=schedule.next_fire_after(now),
        cancel_active_run=cancel_active,
        exhausted=exhausted,
        enumeration_incomplete=incomplete,
        enumeration_stopped_at=stopped_at,
        window_clamped=window_clamped,
    )


def _fresh_boundary(now: datetime) -> datetime:
    """Occurrences older than this are backfills rather than on-time fires.

    One minute is the finest cadence the cron grammar expresses, so anything
    older than that was missed rather than merely noticed a moment late.
    """
    return now - timedelta(minutes=1)
