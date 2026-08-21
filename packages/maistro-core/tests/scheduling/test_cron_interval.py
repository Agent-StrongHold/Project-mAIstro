"""Tests for the 15-minute minimum-interval invariant in cron validation.

Regression coverage for the bypass where the guard only fired for the
'*/N * * * *' form (and '* * * * *'), letting list/range/step-in-hour
forms with sub-15-minute gaps slip through on both create and update paths.
"""

from __future__ import annotations

import pytest

from maistro.scheduling.store import (
    InMemoryScheduleStore,
    ScheduledTask,
    validate_cron,
)

# Expressions whose implied fire-times have a minimum gap < 15 minutes.
TOO_FREQUENT = [
    "* * * * *",  # every minute
    "*/5 * * * *",  # every 5 minutes
    "*/10 * * * *",  # every 10 minutes
    "0,5,10 * * * *",  # list: 5-minute gaps
    "0-30 * * * *",  # range: 1-minute gaps
    "* */2 * * *",  # every minute, every other hour
    "0 * * * *",  # would be fine on its own, but...
    "*/14 * * * *",  # 14-minute step
    "0,10,20,30,40,50 * * * *",  # 10-minute list
    "0,20,30 * * * *",  # mixed gaps; min gap is 10
    "0,10 0-5 * * *",  # list minute + hour range; 10-min gap
]
# "0 * * * *" is hourly and should be ACCEPTED — moved to OK below.
TOO_FREQUENT.remove("0 * * * *")

OK = [
    "*/15 * * * *",  # every 15 minutes
    "*/30 * * * *",  # every 30 minutes
    "0,30 * * * *",  # half-hourly list
    "0,15,30,45 * * * *",  # quarter-hourly list
    "0 * * * *",  # hourly
    "0 0 * * *",  # daily
    "15,45 * * * *",  # 30-min gaps (wraps 45->15 = 30)
    "0,15,30,45 9-17 * * 1-5",  # business-hours quarter-hourly
]


@pytest.mark.parametrize("expr", TOO_FREQUENT)
def test_validate_cron_rejects_sub_15_minute(expr: str) -> None:
    with pytest.raises(ValueError, match="15 min"):
        validate_cron(expr)


@pytest.mark.parametrize("expr", OK)
def test_validate_cron_accepts_15_minute_or_slower(expr: str) -> None:
    validate_cron(expr)  # must not raise


@pytest.mark.asyncio
@pytest.mark.parametrize("expr", ["0,5,10 * * * *", "0-30 * * * *", "* */2 * * *"])
async def test_create_rejects_sub_15_minute(expr: str) -> None:
    store = InMemoryScheduleStore()
    with pytest.raises(ValueError, match="15 min"):
        await store.create(ScheduledTask(user_id="u1", name="t", schedule=expr))


@pytest.mark.asyncio
@pytest.mark.parametrize("expr", ["0,5,10 * * * *", "0-30 * * * *", "* */2 * * *"])
async def test_update_rejects_sub_15_minute(expr: str) -> None:
    store = InMemoryScheduleStore()
    task = await store.create(ScheduledTask(user_id="u1", name="t", schedule="*/15 * * * *"))
    with pytest.raises(ValueError, match="15 min"):
        await store.update(task.id, schedule=expr)
