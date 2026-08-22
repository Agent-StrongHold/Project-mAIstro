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

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

from maistro.scheduling.model import OverlapPolicy, Schedule

__all__ = [
    "FireDecision",
    "ScheduleEvaluation",
    "SkipReason",
    "SkippedFire",
    "evaluate",
]

# How many occurrences one evaluation will carry. The catchup window is the
# real bound — at one-minute granularity a one-hour window holds 60 and a
# one-day window 1440 — and this caps what a single decision returns.
_MAX_ENUMERATED_FIRES: Final = 512

# Backstop on the walk itself, not a working limit: it must stay far above any
# realistic window so the newest occurrences are always reached, since those
# are the ones a caller still wants to act on. 50k covers roughly a month of
# per-minute fires.
_MAX_WALK_STEPS: Final = 50_000


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


def _enumerate_due(
    schedule: Schedule, *, since: datetime, now: datetime
) -> tuple[list[datetime], list[datetime]]:
    """Occurrences in (since, now], oldest first, plus any dropped by the cap.

    When more occurrences are due than one evaluation will carry, the *newest*
    are kept: they are the ones a caller still wants to act on. The older
    remainder is returned separately so it can be reported rather than
    vanishing.
    """
    occurrences: list[datetime] = []
    cursor = since
    while True:
        cursor = schedule.next_fire_after(cursor)
        if cursor > now:
            break
        occurrences.append(cursor)
        if len(occurrences) >= _MAX_WALK_STEPS:
            # Only reachable with an absurd window; stop rather than walk
            # forever. The split below still keeps the newest of what we saw.
            break
    if len(occurrences) <= _MAX_ENUMERATED_FIRES:
        return occurrences, []
    split = len(occurrences) - _MAX_ENUMERATED_FIRES
    return occurrences[split:], occurrences[:split]


def _catchup_horizon(schedule: Schedule, *, now: datetime) -> datetime:
    return now - timedelta(seconds=schedule.catchup_window_seconds)


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


def evaluate(
    schedule: Schedule,
    *,
    now: datetime,
    active_run: bool = False,
) -> ScheduleEvaluation:
    """Decide what a schedule should do at ``now``.

    ``active_run`` is whether a Run this schedule started is still in flight;
    the caller answers that from Run state, which is the only place it lives.
    """
    if not schedule.enabled:
        return ScheduleEvaluation(next_due_at=None)
    if schedule.exhausted:
        return ScheduleEvaluation(next_due_at=None, exhausted=True)

    horizon = _catchup_horizon(schedule, now=now)
    # Three lower bounds, all of them real: the catchup window (which bounds
    # both the semantics and the size of the walk), the last fire, and the
    # moment the schedule came into existence — creating a schedule must not
    # retroactively schedule work from before it existed.
    since = max(schedule.last_fired_at or horizon, horizon, schedule.created_at)
    occurrences, truncated = _enumerate_due(schedule, since=since, now=now)
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
    )


def _fresh_boundary(now: datetime) -> datetime:
    """Occurrences older than this are backfills rather than on-time fires.

    One minute is the finest cadence the cron grammar expresses, so anything
    older than that was missed rather than merely noticed a moment late.
    """
    return now - timedelta(minutes=1)
