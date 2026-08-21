"""Schedule persistence, asserted identically against both implementations.

Every test runs against the in-memory store and the SQLite store, because the
failure this layer exists to prevent — a schedule that quietly stops existing
— is exactly what a store that drifts from its protocol reintroduces.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import aiosqlite
import pytest

from maistro.scheduling.model import Schedule
from maistro.scheduling.store import (
    InMemoryScheduleStore,
    ScheduleStore,
    SqliteScheduleStore,
)

NOON = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _schedule(**overrides: object) -> Schedule:
    defaults: dict[str, object] = {
        "workspace_id": "w1",
        "project_id": "p1",
        "cron": "0 * * * *",
        "graph_template_id": "daily-status",
    }
    return Schedule(**{**defaults, **overrides})  # type: ignore[arg-type]


@pytest.fixture(params=["memory", "sqlite"])
async def store(request: pytest.FixtureRequest, tmp_path) -> AsyncIterator[ScheduleStore]:
    if request.param == "memory":
        yield InMemoryScheduleStore()
        return
    async with aiosqlite.connect(tmp_path / "schedules.db") as conn:
        sqlite_store = SqliteScheduleStore(conn)
        await sqlite_store.ensure_schema()
        yield sqlite_store


async def test_put_and_get_round_trip(store: ScheduleStore) -> None:
    schedule = _schedule(name="briefing", timezone="America/New_York", inputs={"k": "v"})
    await store.put(schedule)
    loaded = await store.get(schedule.schedule_id)
    assert loaded is not None
    assert loaded.name == "briefing"
    assert loaded.timezone == "America/New_York"
    assert loaded.inputs == {"k": "v"}
    assert loaded.graph_template_id == "daily-status"


async def test_get_unknown_returns_none(store: ScheduleStore) -> None:
    assert await store.get("nope") is None


async def test_put_replaces_an_existing_schedule(store: ScheduleStore) -> None:
    schedule = _schedule(name="before")
    await store.put(schedule)
    await store.put(schedule.model_copy(update={"name": "after"}))
    loaded = await store.get(schedule.schedule_id)
    assert loaded is not None and loaded.name == "after"
    assert len(await store.list_for_project(workspace_id="w1", project_id="p1")) == 1


async def test_delete(store: ScheduleStore) -> None:
    schedule = await store.put(_schedule())
    assert await store.delete(schedule.schedule_id) is True
    assert await store.delete(schedule.schedule_id) is False
    assert await store.get(schedule.schedule_id) is None


async def test_list_is_scoped_to_one_project(store: ScheduleStore) -> None:
    await store.put(_schedule(name="mine"))
    await store.put(_schedule(name="other-project", project_id="p2"))
    await store.put(_schedule(name="other-workspace", workspace_id="w2"))
    listed = await store.list_for_project(workspace_id="w1", project_id="p1")
    assert [s.name for s in listed] == ["mine"]


# --- due-ness ---------------------------------------------------------------


async def test_due_returns_schedules_whose_cursor_has_arrived(store: ScheduleStore) -> None:
    await store.put(_schedule(name="ready", next_due_at=NOON - timedelta(minutes=1)))
    await store.put(_schedule(name="later", next_due_at=NOON + timedelta(hours=1)))
    assert [s.name for s in await store.due(now=NOON)] == ["ready"]


async def test_a_schedule_with_no_cursor_is_due(store: ScheduleStore) -> None:
    """An unknown cursor must be evaluated, never treated as not-due — that is
    how a freshly created schedule would never fire."""
    await store.put(_schedule(name="fresh", next_due_at=None))
    assert [s.name for s in await store.due(now=NOON)] == ["fresh"]


async def test_disabled_schedules_are_never_due(store: ScheduleStore) -> None:
    await store.put(_schedule(name="paused", enabled=False, next_due_at=NOON - timedelta(days=1)))
    assert await store.due(now=NOON) == []


# --- fire cursor ----------------------------------------------------------------


async def test_record_fire_advances_the_cursor(store: ScheduleStore) -> None:
    schedule = await store.put(_schedule(runs_so_far=2))
    advanced = await store.record_fire(
        schedule.schedule_id,
        fired_at=NOON,
        run_id="run-123",
        next_due_at=NOON + timedelta(hours=1),
    )
    assert advanced is not None
    assert advanced.last_fired_at == NOON
    assert advanced.last_run_id == "run-123"
    assert advanced.runs_so_far == 3
    assert advanced.next_due_at == NOON + timedelta(hours=1)
    # ...and it is the persisted state, not just the returned object.
    reloaded = await store.get(schedule.schedule_id)
    assert reloaded is not None and reloaded.runs_so_far == 3


async def test_record_fire_can_advance_by_several_backfilled_fires(
    store: ScheduleStore,
) -> None:
    schedule = await store.put(_schedule())
    advanced = await store.record_fire(
        schedule.schedule_id, fired_at=NOON, run_id=None, next_due_at=None, fires=3
    )
    assert advanced is not None and advanced.runs_so_far == 3


async def test_disable_on_exhaustion_stops_the_schedule_being_due(
    store: ScheduleStore,
) -> None:
    schedule = await store.put(_schedule(max_runs=1))
    await store.record_fire(
        schedule.schedule_id,
        fired_at=NOON,
        run_id="run-1",
        next_due_at=NOON + timedelta(hours=1),
        disable=True,
    )
    reloaded = await store.get(schedule.schedule_id)
    assert reloaded is not None
    assert reloaded.enabled is False and reloaded.next_due_at is None
    assert await store.due(now=NOON + timedelta(days=1)) == []


async def test_record_fire_on_unknown_schedule_returns_none(store: ScheduleStore) -> None:
    assert (
        await store.record_fire("nope", fired_at=NOON, run_id=None, next_due_at=None)
    ) is None


# --- the actual defect --------------------------------------------------------


async def test_sqlite_schedules_survive_a_reconnect(tmp_path) -> None:
    """The whole point: a schedule created before a restart still exists,
    still enabled, with its cursor intact."""
    path = tmp_path / "durable.db"
    async with aiosqlite.connect(path) as first:
        store = SqliteScheduleStore(first)
        await store.ensure_schema()
        schedule = await store.put(_schedule(name="briefing", cron="0 7 * * 1-5"))
        await store.record_fire(
            schedule.schedule_id,
            fired_at=NOON,
            run_id="run-abc",
            next_due_at=NOON + timedelta(hours=19),
        )

    async with aiosqlite.connect(path) as second:
        reopened = SqliteScheduleStore(second)
        await reopened.ensure_schema()
        survivor = await reopened.get(schedule.schedule_id)

    assert survivor is not None
    assert survivor.name == "briefing" and survivor.enabled is True
    assert survivor.last_run_id == "run-abc"
    assert survivor.next_due_at == NOON + timedelta(hours=19)


def test_both_implementations_satisfy_the_protocol() -> None:
    assert isinstance(InMemoryScheduleStore(), ScheduleStore)
