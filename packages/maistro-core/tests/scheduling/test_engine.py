"""Fire semantics: catchup after downtime, overlap, and bounded recurrence.

These are the decisions neither predecessor design specified. They are pure
functions of (schedule, now, active_run), so they get asserted directly
rather than inferred from the behaviour of a polling loop.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from maistro.scheduling.engine import SkipReason, evaluate
from maistro.scheduling.model import OverlapPolicy, Schedule

NOON = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _schedule(**overrides: object) -> Schedule:
    defaults: dict[str, object] = {
        "workspace_id": "w1",
        "project_id": "p1",
        "name": "hourly",
        "cron": "0 * * * *",
        "graph_template_id": "daily-status",
        # Real schedules predate the moment they are evaluated; the default
        # factory would stamp *now*, which is after these fixed test instants.
        "created_at": NOON - timedelta(days=30),
    }
    return Schedule(**{**defaults, **overrides})  # type: ignore[arg-type]


# --- due-ness ---------------------------------------------------------------


def test_nothing_due_yields_no_fires_but_still_reports_next_due() -> None:
    schedule = _schedule(last_fired_at=NOON)
    result = evaluate(schedule, now=NOON + timedelta(minutes=30))
    assert result.fires == ()
    assert result.next_due_at == datetime(2026, 8, 21, 13, 0, tzinfo=UTC)


def test_an_occurrence_that_came_due_fires_once() -> None:
    schedule = _schedule(last_fired_at=NOON)
    result = evaluate(schedule, now=NOON + timedelta(hours=1, seconds=5))
    assert [f.scheduled_for for f in result.fires] == [datetime(2026, 8, 21, 13, 0, tzinfo=UTC)]
    assert result.fires[0].catchup is False


def test_a_never_fired_schedule_starts_from_the_catchup_horizon() -> None:
    """No last_fired_at must not mean "replay from the epoch"."""
    result = evaluate(_schedule(), now=NOON)
    assert len(result.fires) <= 1
    assert result.next_due_at == datetime(2026, 8, 21, 13, 0, tzinfo=UTC)


# --- catchup after downtime -------------------------------------------------


def test_missed_occurrences_inside_the_window_are_backfilled_as_catchup() -> None:
    schedule = _schedule(
        cron="*/15 * * * *",
        last_fired_at=NOON,
        overlap_policy=OverlapPolicy.ALLOW,
        catchup_window_seconds=3600,
    )
    result = evaluate(schedule, now=NOON + timedelta(minutes=46))
    assert [f.scheduled_for.minute for f in result.fires] == [15, 30, 45]
    # The two stale occurrences are backfills; 12:45 is a minute old, which is
    # an on-time fire noticed a tick late rather than a missed one.
    assert [f.catchup for f in result.fires] == [True, True, False]


def test_occurrences_older_than_the_catchup_window_are_dropped_deliberately() -> None:
    """After a long outage, replaying every missed fire is a stampede."""
    schedule = _schedule(
        cron="0 * * * *",
        last_fired_at=NOON - timedelta(hours=10),
        overlap_policy=OverlapPolicy.ALLOW,
        catchup_window_seconds=3600,
    )
    result = evaluate(schedule, now=NOON)
    assert len(result.fires) <= 1
    assert all(s.reason is SkipReason.OUTSIDE_CATCHUP for s in result.skipped)


def test_a_zero_catchup_window_refuses_all_backfill() -> None:
    schedule = _schedule(last_fired_at=NOON, catchup_window_seconds=0.0)
    result = evaluate(schedule, now=NOON + timedelta(hours=2))
    assert result.fires == ()


# --- overlap ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("policy", "expected_fires"),
    [
        (OverlapPolicy.SKIP, 0),
        (OverlapPolicy.ALLOW, 1),
        (OverlapPolicy.CANCEL_OTHER, 1),
        # Buffering is not concurrency: nothing runs until the active Run ends.
        (OverlapPolicy.BUFFER_ONE, 0),
    ],
)
def test_overlap_policy_governs_firing_while_a_run_is_in_flight(
    policy: OverlapPolicy, expected_fires: int
) -> None:
    schedule = _schedule(last_fired_at=NOON, overlap_policy=policy)
    result = evaluate(schedule, now=NOON + timedelta(hours=1), active_run=True)
    assert len(result.fires) == expected_fires


def test_skip_records_why_it_did_not_fire() -> None:
    schedule = _schedule(last_fired_at=NOON, overlap_policy=OverlapPolicy.SKIP)
    result = evaluate(schedule, now=NOON + timedelta(hours=1), active_run=True)
    assert [s.reason for s in result.skipped] == [SkipReason.OVERLAP]


def test_cancel_other_asks_the_caller_to_cancel_the_in_flight_run() -> None:
    schedule = _schedule(last_fired_at=NOON, overlap_policy=OverlapPolicy.CANCEL_OTHER)
    active = evaluate(schedule, now=NOON + timedelta(hours=1), active_run=True)
    assert active.cancel_active_run is True
    idle = evaluate(schedule, now=NOON + timedelta(hours=1), active_run=False)
    assert idle.cancel_active_run is False


def test_backfilled_occurrences_overlap_the_run_the_first_one_starts() -> None:
    """With SKIP and three missed occurrences, the first becomes the in-flight
    Run and the rest are overlapped — not three concurrent Runs."""
    schedule = _schedule(cron="*/15 * * * *", last_fired_at=NOON, overlap_policy=OverlapPolicy.SKIP)
    result = evaluate(schedule, now=NOON + timedelta(minutes=46))
    assert len(result.fires) == 1
    assert [s.reason for s in result.skipped] == [SkipReason.OVERLAP, SkipReason.OVERLAP]


# --- bounded recurrence --------------------------------------------------------


def test_max_runs_caps_fires_and_reports_exhaustion() -> None:
    schedule = _schedule(
        cron="*/15 * * * *",
        last_fired_at=NOON,
        overlap_policy=OverlapPolicy.ALLOW,
        max_runs=5,
        runs_so_far=3,
    )
    result = evaluate(schedule, now=NOON + timedelta(minutes=46))
    assert len(result.fires) == 2
    assert result.exhausted is True
    assert [s.reason for s in result.skipped] == [SkipReason.EXHAUSTED]


def test_an_already_exhausted_schedule_does_nothing() -> None:
    schedule = _schedule(last_fired_at=NOON, max_runs=2, runs_so_far=2)
    result = evaluate(schedule, now=NOON + timedelta(hours=5))
    assert result.fires == ()
    assert result.exhausted is True
    assert result.next_due_at is None


def test_a_disabled_schedule_does_nothing() -> None:
    schedule = _schedule(last_fired_at=NOON, enabled=False)
    result = evaluate(schedule, now=NOON + timedelta(hours=5))
    assert result.fires == () and result.next_due_at is None


# --- invariants ------------------------------------------------------------------


@given(
    minutes_elapsed=st.integers(min_value=0, max_value=240),
    policy=st.sampled_from(list(OverlapPolicy)),
    active=st.booleans(),
    max_runs=st.one_of(st.none(), st.integers(min_value=1, max_value=4)),
)
def test_every_due_occurrence_is_either_fired_or_explains_itself(
    minutes_elapsed: int, policy: OverlapPolicy, active: bool, max_runs: int | None
) -> None:
    """Nothing vanishes silently: each occurrence in the evaluated window is
    accounted for exactly once, as a fire or as a skip with a reason."""
    schedule = _schedule(
        cron="*/15 * * * *",
        last_fired_at=NOON,
        overlap_policy=policy,
        max_runs=max_runs,
        catchup_window_seconds=86_400,
    )
    now = NOON + timedelta(minutes=minutes_elapsed)
    result = evaluate(schedule, now=now, active_run=active)

    expected: list[datetime] = []
    cursor = NOON
    while (cursor := schedule.next_fire_after(cursor)) <= now:
        expected.append(cursor)

    accounted = [f.scheduled_for for f in result.fires] + [s.scheduled_for for s in result.skipped]
    assert sorted(accounted) == expected
    assert len(accounted) == len(set(accounted))


@given(
    runs_so_far=st.integers(min_value=0, max_value=6),
    max_runs=st.integers(min_value=1, max_value=6),
)
def test_fires_never_exceed_the_remaining_run_budget(runs_so_far: int, max_runs: int) -> None:
    schedule = _schedule(
        cron="*/15 * * * *",
        last_fired_at=NOON,
        overlap_policy=OverlapPolicy.ALLOW,
        max_runs=max_runs,
        runs_so_far=runs_so_far,
        catchup_window_seconds=86_400,
    )
    result = evaluate(schedule, now=NOON + timedelta(hours=3))
    assert len(result.fires) <= max(0, max_runs - runs_so_far)


# --- review findings, locked ---------------------------------------------------


def test_creation_does_not_retroactively_schedule_work() -> None:
    """A newly created schedule must not treat occurrences from before it
    existed as missed work: an hourly schedule created just after the hour
    waits for its first future occurrence."""
    created = datetime(2026, 8, 21, 12, 1, tzinfo=UTC)
    schedule = _schedule(cron="0 * * * *", created_at=created, last_fired_at=None)
    result = evaluate(schedule, now=created + timedelta(seconds=30))
    assert result.fires == ()
    assert result.next_due_at == datetime(2026, 8, 21, 13, 0, tzinfo=UTC)


def test_a_minutely_schedule_does_not_backfill_an_hour_on_creation() -> None:
    created = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    schedule = _schedule(
        cron="* * * * *",
        created_at=created,
        last_fired_at=None,
        overlap_policy=OverlapPolicy.ALLOW,
    )
    result = evaluate(schedule, now=created + timedelta(seconds=30))
    assert result.fires == ()


def test_occurrences_beyond_the_enumeration_cap_are_reported_not_dropped() -> None:
    """A caller that advances its cursor on this decision must not lose
    occurrences without a record. The newest are kept; the remainder is
    reported as truncated."""
    schedule = _schedule(
        cron="* * * * *",
        last_fired_at=NOON - timedelta(days=1),
        overlap_policy=OverlapPolicy.ALLOW,
        catchup_window_seconds=86_400,
        created_at=NOON - timedelta(days=30),
    )
    result = evaluate(schedule, now=NOON)
    accounted = [f.scheduled_for for f in result.fires] + [s.scheduled_for for s in result.skipped]
    assert len(accounted) == 1440  # every minute of the window
    assert any(s.reason is SkipReason.TRUNCATED for s in result.skipped)
    # The newest occurrences survive — they are the ones still worth running.
    assert max(accounted) == NOON


def test_buffer_one_never_runs_alongside_an_active_run() -> None:
    """BUFFER_ONE means "one queued occurrence afterwards", not "run it now"."""
    schedule = _schedule(
        cron="*/15 * * * *",
        last_fired_at=NOON,
        overlap_policy=OverlapPolicy.BUFFER_ONE,
    )
    result = evaluate(schedule, now=NOON + timedelta(minutes=46), active_run=True)
    assert result.fires == ()
    assert [s.reason for s in result.skipped].count(SkipReason.BUFFERED) == 1


def test_buffer_one_holds_at_most_one_when_idle() -> None:
    """Idle: the first occurrence runs, exactly one is held for afterwards, and
    the rest are dropped."""
    schedule = _schedule(
        cron="*/15 * * * *",
        last_fired_at=NOON,
        overlap_policy=OverlapPolicy.BUFFER_ONE,
    )
    result = evaluate(schedule, now=NOON + timedelta(minutes=46), active_run=False)
    assert len(result.fires) == 1
    reasons = [s.reason for s in result.skipped]
    assert reasons.count(SkipReason.BUFFERED) == 1
    assert reasons.count(SkipReason.OVERLAP) == 1


def test_a_buffered_occurrence_becomes_due_again_once_the_run_ends() -> None:
    """The held occurrence is not consumed: its cursor never advanced, so the
    next evaluation with nothing active runs it."""
    schedule = _schedule(
        cron="0 * * * *", last_fired_at=NOON, overlap_policy=OverlapPolicy.BUFFER_ONE
    )
    now = NOON + timedelta(hours=1, minutes=5)
    assert evaluate(schedule, now=now, active_run=True).fires == ()
    later = evaluate(schedule, now=now, active_run=False)
    assert [f.scheduled_for for f in later.fires] == [datetime(2026, 8, 21, 13, 0, tzinfo=UTC)]
