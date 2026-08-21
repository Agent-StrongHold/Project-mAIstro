"""Minimum-interval enforcement, ported to the real gap computation.

Regression coverage for a bypass where the old guard only fired for the
`*/N * * * *` form, letting list/range/step-in-hour forms with sub-15-minute
gaps through. That guard estimated the gap from the minute and hour fields
alone; `minimum_gap` measures it from actual consecutive fire times, so the
day-of-month and day-of-week fields count too.

The 15-minute floor itself is a *product* policy, not a substrate rule — the
substrate supplies the measurement and each product enforces its own limit,
which is what `_rejects` models here.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from maistro.scheduling.cron import minimum_gap
from maistro.scheduling.model import Schedule

PRODUCT_FLOOR = timedelta(minutes=15)

TOO_FREQUENT = [
    "* * * * *",  # every minute
    "*/5 * * * *",  # every 5 minutes
    "*/10 * * * *",  # every 10 minutes
    "0,5,10 * * * *",  # list: 5-minute gaps
    "0-30 * * * *",  # range: 1-minute gaps
    "* */2 * * *",  # every minute, every other hour
    "*/14 * * * *",  # 14-minute step
    "0,10,20,30,40,50 * * * *",  # 10-minute list
    "0,20,30 * * * *",  # mixed gaps; min gap is 10
    "0,10 0-5 * * *",  # list minute + hour range; 10-min gap
]

OK = [
    "*/15 * * * *",  # every 15 minutes
    "*/30 * * * *",  # every 30 minutes
    "0,30 * * * *",  # half-hourly list
    "0,15,30,45 * * * *",  # quarter-hourly list
    "0 * * * *",  # hourly
    "0 0 * * *",  # daily
    "15,45 * * * *",  # 30-min gaps (wraps 45->15 = 30)
    "0,15,30,45 9-17 * * 1-5",  # business-hours quarter-hourly
    "0 9 * * 1-5",  # weekday mornings
    "0 0 1 * *",  # monthly
    "0 0 1 3 *",  # a single fire each March
]


def _rejects(expression: str) -> bool:
    """What a product route does: measure, then apply its own floor."""
    return minimum_gap(expression) < PRODUCT_FLOOR


@pytest.mark.parametrize("expression", TOO_FREQUENT)
def test_sub_floor_expressions_are_measured_as_too_frequent(expression: str) -> None:
    assert _rejects(expression)


@pytest.mark.parametrize("expression", OK)
def test_at_or_above_the_floor_is_accepted(expression: str) -> None:
    assert not _rejects(expression)


def test_gap_accounts_for_the_wrap_between_hours() -> None:
    """`15,45 * * * *` is 30-minute spacing only if the 45 -> next-hour-15 wrap
    is measured; a naive within-hour diff reports 30 for the wrong reason."""
    assert minimum_gap("15,45 * * * *") == timedelta(minutes=30)


def test_gap_accounts_for_day_fields_the_old_estimator_ignored() -> None:
    """Hour and minute alone would call this quarter-hourly; the day-of-week
    restriction does not change the minimum gap, but the measurement now
    genuinely considers it rather than assuming."""
    assert minimum_gap("0,15,30,45 9-17 * * 1-5") == timedelta(minutes=15)


def test_a_schedule_exposes_its_own_gap_for_product_enforcement() -> None:
    schedule = Schedule(
        workspace_id="w1",
        project_id="p1",
        cron="*/5 * * * *",
        graph_template_id="daily-status",
    )
    assert schedule.minimum_gap() == timedelta(minutes=5)
    assert schedule.minimum_gap() < PRODUCT_FLOOR


def test_month_restricted_expressions_are_measured_where_they_actually_fire() -> None:
    """Regression: sampling a fixed calendar window anchored in January saw no
    fires at all for a March-only expression and reported it as unbounded — the
    dangerous direction, because a product floor would then accept a schedule
    that really fires ten minutes apart."""
    assert minimum_gap("0,10 0 1 3 *") == timedelta(minutes=10)
    assert _rejects("0,10 0 1 3 *")


def test_yearly_schedules_report_their_real_spacing() -> None:
    assert minimum_gap("0 0 1 1 *") == timedelta(days=365)
    assert not _rejects("0 0 1 1 *")


def test_a_recurrence_rarer_than_the_horizon_reports_unbounded() -> None:
    """Feb 29 fires once inside the four-year sample; with no consecutive pair
    to measure, the gap is unbounded — safe, since the true spacing is years."""
    assert minimum_gap("0 0 29 2 *") == timedelta.max
