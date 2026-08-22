"""POSIX cron: correctness against a brute-force oracle, plus DST rules.

`next_fire` advances a whole month/day/hour when a coarse field cannot match,
which is what makes it fast — and what could make it skip a fire. The oracle
property scans minute by minute and asserts the two agree, so the fast walk
is verified rather than merely reviewed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from maistro.scheduling.cron import CronParseError, parse_cron

NY = ZoneInfo("America/New_York")


def _brute_force_next(expression: str, after: datetime, *, limit_minutes: int) -> datetime | None:
    """Naive oracle: the first minute strictly after `after` that matches."""
    parsed = parse_cron(expression)
    cursor = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(limit_minutes):
        if parsed.matches(cursor):
            return cursor
        cursor += timedelta(minutes=1)
    return None


_MINUTES = st.sampled_from(["*", "0", "30", "*/15", "0,30", "5-10", "0-59/20"])
_HOURS = st.sampled_from(["*", "0", "9", "*/6", "9-17", "0,12"])
_DOM = st.sampled_from(["*", "1", "15", "1,15", "*/10", "28-31"])
_MONTHS = st.sampled_from(["*", "1", "2", "*/3", "JAN", "1,6,12"])
_DOW = st.sampled_from(["*", "0", "1", "5", "MON", "1-5", "0,6", "7"])


@st.composite
def _cron(draw: st.DrawFn) -> str:
    return " ".join((draw(_MINUTES), draw(_HOURS), draw(_DOM), draw(_MONTHS), draw(_DOW)))


@settings(max_examples=200, deadline=None)
@given(
    expression=_cron(),
    offset_minutes=st.integers(min_value=0, max_value=370 * 24 * 60),
)
def test_next_fire_agrees_with_brute_force_scan(expression: str, offset_minutes: int) -> None:
    """The fast advance never skips a fire the minute-by-minute scan finds."""
    start = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=offset_minutes)
    # Two years of minutes covers every generated expression, Feb-29 included.
    expected = _brute_force_next(expression, start, limit_minutes=2 * 366 * 24 * 60)
    assert expected is not None, "oracle found no fire; widen the scan window"
    actual = parse_cron(expression).next_fire(start)
    assert actual.replace(tzinfo=None) == expected.replace(tzinfo=None)


@settings(max_examples=100, deadline=None)
@given(expression=_cron(), offset_minutes=st.integers(min_value=0, max_value=100_000))
def test_next_fire_is_strictly_after_and_matches(expression: str, offset_minutes: int) -> None:
    start = datetime(2026, 3, 1, tzinfo=UTC) + timedelta(minutes=offset_minutes)
    parsed = parse_cron(expression)
    fire = parsed.next_fire(start)
    assert fire > start
    assert parsed.matches(fire)


# --- the two bugs this module exists to kill --------------------------------


def test_day_of_week_zero_is_sunday_not_monday() -> None:
    """The shipped matcher indexed DOW by date.weekday() (Monday=0), so every
    `0`-means-Sunday expression fired a day late."""
    fire = parse_cron("0 9 * * 0").next_fire(datetime(2026, 8, 19, tzinfo=UTC))
    assert fire.strftime("%A") == "Sunday"
    assert fire == datetime(2026, 8, 23, 9, 0, tzinfo=UTC)


def test_day_of_week_seven_is_also_sunday() -> None:
    assert parse_cron("0 9 * * 7").next_fire(datetime(2026, 8, 19, tzinfo=UTC)) == parse_cron(
        "0 9 * * 0"
    ).next_fire(datetime(2026, 8, 19, tzinfo=UTC))


def test_restricted_dom_and_dow_are_ored_not_anded() -> None:
    """POSIX: `0 0 1 * 1` is "the 1st, OR any Monday". The shipped matcher
    ANDed them, turning ~5 fires a month into one every seven months."""
    parsed = parse_cron("0 0 1 * 1")
    assert parsed.matches(datetime(2026, 9, 1, 0, 0))  # a Tuesday, but the 1st
    assert parsed.matches(datetime(2026, 9, 7, 0, 0))  # a Monday, not the 1st
    assert not parsed.matches(datetime(2026, 9, 8, 0, 0))  # neither

    fires = []
    cursor = datetime(2026, 8, 31, 12, tzinfo=UTC)
    for _ in range(6):
        cursor = parsed.next_fire(cursor)
        fires.append(cursor)
    # Five distinct September days (the 1st plus four Mondays), not one.
    assert len({f.day for f in fires if f.month == 9}) >= 5


def test_unrestricted_day_field_does_not_gate_the_other() -> None:
    assert parse_cron("0 0 * * 1").matches(datetime(2026, 9, 7, 0, 0))
    assert not parse_cron("0 0 * * 1").matches(datetime(2026, 9, 8, 0, 0))
    assert parse_cron("0 0 15 * *").matches(datetime(2026, 9, 15, 0, 0))


# --- names, steps, ranges ---------------------------------------------------


def test_named_month_and_day_fields() -> None:
    assert (
        parse_cron("0 9 * * MON").next_fire(datetime(2026, 8, 19, tzinfo=UTC)).strftime("%A")
        == "Monday"
    )
    assert parse_cron("0 0 1 jan *").next_fire(datetime(2026, 6, 1, tzinfo=UTC)) == datetime(
        2027, 1, 1, 0, 0, tzinfo=UTC
    )


def test_leap_day_expression_converges() -> None:
    """`0 0 29 2 *` is the pathological case for a minute-stepping search."""
    assert parse_cron("0 0 29 2 *").next_fire(datetime(2026, 3, 1, tzinfo=UTC)) == datetime(
        2028, 2, 29, 0, 0, tzinfo=UTC
    )


@pytest.mark.parametrize(
    "expression",
    [
        "* * * *",
        "* * * * * *",
        "60 * * * *",
        "* 24 * * *",
        "0 0 0 * *",
        "0 0 * 13 *",
        "10-5 * * * *",
        "*/0 * * * *",
        "0 0 * * FUNDAY",
        "",
    ],
)
def test_invalid_expressions_are_rejected(expression: str) -> None:
    with pytest.raises(CronParseError):
        parse_cron(expression)


def test_unknown_timezone_is_rejected() -> None:
    with pytest.raises(CronParseError):
        parse_cron("0 9 * * *").next_fire(
            datetime(2026, 8, 19, tzinfo=UTC), timezone="Mars/Olympus"
        )


# --- DST ---------------------------------------------------------------------


def test_wall_time_is_stable_across_a_dst_transition() -> None:
    """07:00 local stays 07:00 local — the whole point of storing a timezone."""
    # 2026-03-08 02:00 is the US spring-forward; straddle it.
    before = parse_cron("0 7 * * *").next_fire(
        datetime(2026, 3, 6, 12, tzinfo=NY), timezone="America/New_York"
    )
    after = parse_cron("0 7 * * *").next_fire(
        datetime(2026, 3, 8, 12, tzinfo=NY), timezone="America/New_York"
    )
    assert before.hour == 7 and after.hour == 7
    # ...even though the UTC offset moved under it.
    assert before.utcoffset() != after.utcoffset()


def test_nonexistent_wall_time_in_the_spring_forward_gap_is_skipped() -> None:
    """02:30 does not exist on the US spring-forward day; the schedule fires at
    its next valid occurrence rather than at a time nobody asked for."""
    fire = parse_cron("30 2 * * *").next_fire(
        datetime(2026, 3, 7, 12, tzinfo=NY), timezone="America/New_York"
    )
    assert fire.date() == datetime(2026, 3, 9).date()
    assert (fire.hour, fire.minute) == (2, 30)


def test_ambiguous_wall_time_in_the_fall_back_fires_once() -> None:
    """01:30 happens twice on the fall-back day; only the first fires."""
    first = parse_cron("30 1 * * *").next_fire(
        datetime(2026, 10, 31, 12, tzinfo=NY), timezone="America/New_York"
    )
    assert (first.month, first.day, first.hour, first.minute) == (11, 1, 1, 30)
    following = parse_cron("30 1 * * *").next_fire(first, timezone="America/New_York")
    assert (following.month, following.day) == (11, 2)


def test_naive_after_is_read_as_wall_time_in_the_zone() -> None:
    fire = parse_cron("0 9 * * *").next_fire(
        datetime(2026, 8, 19, 8, 0), timezone="America/New_York"
    )
    assert (fire.hour, fire.tzinfo) == (9, NY)
