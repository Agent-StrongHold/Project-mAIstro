"""The bounded catch-up work contract (#1200).

One evaluation's catch-up walk is the only place the scheduling substrate
does unbounded CPU work on a shared event loop: the audit behind #1200
measured 50,000 cron reparses taking ~0.64s synchronously for one stale
per-minute schedule. These tests pin the three axes the work can grow on —
window, occurrences, wall clock — as host-selected bounds, and the truthful
semantics required when a bound stops the walk early: the unexamined range is
reported, never claimed to have been considered.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from maistro.scheduling.engine import (
    DEFAULT_ENUMERATION_LIMITS,
    EnumerationLimits,
    enumeration_start,
    evaluate,
)
from maistro.scheduling.model import MAX_CATCHUP_WINDOW_SECONDS, OverlapPolicy, Schedule

NOON = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
SEVEN_DAYS = 604_800.0


def _schedule(**overrides: object) -> Schedule:
    defaults: dict[str, object] = {
        "workspace_id": "w1",
        "project_id": "p1",
        "name": "minutely",
        "cron": "* * * * *",
        "graph_template_id": "daily-status",
        "overlap_policy": OverlapPolicy.ALLOW,
        # Real schedules predate the moment they are evaluated; the default
        # factory would stamp *now*, which is after these fixed test instants.
        "created_at": NOON - timedelta(days=30),
        "last_fired_at": NOON - timedelta(days=7),
        "catchup_window_seconds": SEVEN_DAYS,
    }
    return Schedule(**{**defaults, **overrides})  # type: ignore[arg-type]


# --- the limits value object -------------------------------------------------


def test_the_default_step_bound_is_derived_from_the_window_bound() -> None:
    """Cron's finest cadence is one fire per minute, so the window implies the
    step count; the derived default covers the entire possible backlog."""
    assert DEFAULT_ENUMERATION_LIMITS.max_window_seconds == MAX_CATCHUP_WINDOW_SECONDS
    assert DEFAULT_ENUMERATION_LIMITS.walk_steps == math.ceil(SEVEN_DAYS / 60) + 64


def test_out_of_bounds_limits_are_refused_at_construction() -> None:
    for kwargs in (
        {"max_window_seconds": 0},
        {"max_window_seconds": -1.0},
        {"max_walk_steps": 0},
        {"walk_budget_seconds": -0.1},
        {"max_enumerated_fires": 0},
    ):
        try:
            EnumerationLimits(**kwargs)  # type: ignore[arg-type]
        except ValueError:
            continue
        raise AssertionError(f"EnumerationLimits({kwargs}) should have raised")


def test_boundary_values_of_the_limits_are_accepted() -> None:
    limits = EnumerationLimits(
        max_window_seconds=1.0,
        max_walk_steps=1,
        walk_budget_seconds=0.0,
        max_enumerated_fires=1,
    )
    assert limits.walk_steps == 1


# --- the time budget ---------------------------------------------------------


def test_a_zero_budget_stops_before_examining_anything() -> None:
    schedule = _schedule()
    result = evaluate(schedule, now=NOON, limits=EnumerationLimits(walk_budget_seconds=0.0))
    assert result.fires == ()
    assert result.enumeration_incomplete is True
    # Nothing was examined, so the walk stopped where it started.
    assert result.enumeration_stopped_at == enumeration_start(schedule, now=NOON)


def test_an_expired_budget_marks_the_walk_incomplete_at_where_it_stopped() -> None:
    # A backlog far larger than the budget can walk: seven days of per-minute
    # fires against a budget sized for a fraction of them.
    limits = EnumerationLimits(walk_budget_seconds=0.001)
    result = evaluate(_schedule(), now=NOON, limits=limits)
    assert result.enumeration_incomplete is True
    assert result.enumeration_stopped_at is not None
    assert result.enumeration_stopped_at < NOON
    # Every reported occurrence was actually examined: nothing beyond the
    # stop is claimed as fired or skipped. `stopped_at` is the last occurrence
    # the walk had in hand when the budget check fired, so the newest kept
    # fire may equal it; the range strictly past it is the unexamined one.
    for fire in result.fires:
        assert fire.scheduled_for <= result.enumeration_stopped_at
    for skip in result.skipped:
        assert skip.scheduled_for <= result.enumeration_stopped_at


# --- the step bound ----------------------------------------------------------


def test_a_step_bound_tighter_than_the_window_marks_the_walk_incomplete() -> None:
    limits = EnumerationLimits(walk_budget_seconds=math.inf, max_walk_steps=5)
    result = evaluate(_schedule(), now=NOON, limits=limits)
    assert result.enumeration_incomplete is True
    # The five examined occurrences are the *oldest* five (newest are kept
    # only when the batch is split); the stop point is the last one seen.
    assert (
        len(result.fires) + len([s for s in result.skipped if s.reason.value == "outside_catchup"])
        == 5
    )
    # Occurrences land on :01..:05 past the resume point; the walk stopped
    # holding the fifth.
    assert result.enumeration_stopped_at == NOON - timedelta(days=7) + timedelta(minutes=5)


def test_the_derived_step_bound_never_trips_under_the_default_window() -> None:
    """The whole seven-day backlog fits the derived step bound, so with an
    unlimited budget the walk completes and reaches `now`."""
    result = evaluate(_schedule(), now=NOON, limits=EnumerationLimits(walk_budget_seconds=math.inf))
    assert result.enumeration_incomplete is False
    assert result.enumeration_stopped_at is None


# --- the window bound --------------------------------------------------------


def test_a_host_window_bound_smaller_than_the_schedules_is_reported() -> None:
    limits = EnumerationLimits(max_window_seconds=3600.0, walk_budget_seconds=math.inf)
    result = evaluate(_schedule(), now=NOON, limits=limits)
    assert result.window_clamped is True
    # Only the last hour was considered, and it was examined completely.
    assert result.enumeration_incomplete is False
    for fire in result.fires:
        assert fire.scheduled_for >= NOON - timedelta(hours=1)


def test_enumeration_start_honours_the_host_window_bound() -> None:
    schedule = _schedule()
    clamped = enumeration_start(
        schedule, now=NOON, limits=EnumerationLimits(max_window_seconds=3600.0)
    )
    assert clamped == NOON - timedelta(hours=1)
    unclamped = enumeration_start(
        schedule, now=NOON, limits=EnumerationLimits(max_window_seconds=SEVEN_DAYS)
    )
    assert unclamped == schedule.last_fired_at


def test_a_window_within_the_host_bound_is_not_reported_as_clamped() -> None:
    result = evaluate(_schedule(catchup_window_seconds=3600.0), now=NOON)
    assert result.window_clamped is False


# --- bounded wall clock under a 50k-style backlog ----------------------------


def test_a_thirty_day_backlog_enumerates_only_its_catchup_window() -> None:
    """The audit's failure mode, stated as work rather than seconds.

    A stale per-minute schedule stalled the loop for ~0.64s because it reparsed
    every occurrence back to its creation. `_schedule()` is thirty days old, so
    an unbounded evaluation examines ~43,200 of them; the seven-day catchup
    window caps that at 10,080, and `max_enumerated_fires` caps the fire list
    separately.

    The bound is an upper one, not an equality, because `EnumerationLimits`
    stops the walk on *either* of two conditions -- `max_walk_steps` or
    `walk_budget_seconds` (0.1s). A fast machine finishes the window inside the
    budget and examines all 10,080; a loaded one, or one running under coverage
    instrumentation, trips the clock first and truncates honestly. Both satisfy
    the invariant: enumeration never exceeds the window, and never walks the
    thirty-day backlog.

    This asserted `elapsed < 0.5` until #1802, and then briefly asserted
    `seen == 10080`, which was the same mistake wearing a counter -- it
    encoded one machine's speed as a structural fact and failed on slower
    runners. See #184 for the same correction in test_lanes.py.
    """
    result = evaluate(_schedule(), now=NOON)
    seen = len(result.fires) + len(result.skipped)

    # One occurrence per minute, so the window's width is the ceiling on what
    # may be examined -- and it is the schedule's thirty-day age that it
    # refuses. Below it whenever a limit stops the walk sooner.
    assert seen <= int(SEVEN_DAYS // 60)

    # A walk that ran to completion examined the window it was given; only a
    # truncated one may report less. Stated this way round because a budget
    # exhausted on the first step legitimately sees nothing, and asserting a
    # bare `seen > 0` would fail that honest outcome.
    if not result.enumeration_incomplete:
        assert seen > 0

    # Capped independently of the window: a window the engine will examine in
    # full can still hold more fires than one tick should admit.
    assert len(result.fires) <= DEFAULT_ENUMERATION_LIMITS.max_enumerated_fires

    # Bounded work is still honest work. Truncation is reported, and a walk
    # that completed claims no truncation point -- the two must agree in both
    # directions, or a caller cannot tell a full window from a cut-short one.
    assert result.enumeration_incomplete == (result.enumeration_stopped_at is not None)


def test_minutely_occurrences_inside_a_default_window_are_fully_examined() -> None:
    schedule = _schedule(last_fired_at=NOON - timedelta(hours=1), catchup_window_seconds=3600.0)
    result = evaluate(schedule, now=NOON)
    assert result.enumeration_incomplete is False
    assert result.window_clamped is False
    # Enumeration resumes *after* last_fired_at, so the hour holds :01..:00.
    assert [f.scheduled_for for f in result.fires] == [
        NOON - timedelta(minutes=m) for m in range(59, -1, -1)
    ]


def test_normal_catchup_semantics_survive_explicit_limits() -> None:
    """Passing limits must not change what an ordinary evaluation decides."""
    schedule = _schedule(
        cron="*/15 * * * *",
        last_fired_at=NOON,
        catchup_window_seconds=3600.0,
    )
    with_default = evaluate(schedule, now=NOON + timedelta(minutes=46))
    with_explicit = evaluate(
        schedule, now=NOON + timedelta(minutes=46), limits=DEFAULT_ENUMERATION_LIMITS
    )
    assert with_default == with_explicit
    assert [f.scheduled_for.minute for f in with_explicit.fires] == [15, 30, 45]
