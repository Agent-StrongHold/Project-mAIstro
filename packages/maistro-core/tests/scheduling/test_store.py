"""Schedule persistence, asserted identically against every implementation.

Every test runs against all three stores, because the failure this layer
exists to prevent — a schedule that quietly stops existing — is exactly what a
store that drifts from its protocol reintroduces.

PostgreSQL joined the list in #231. It is the only one two processes can
share; `test_concurrent_record_fire_does_not_lose_an_increment` covers two
replicas racing on it. Two *callers* racing on one store — a tick and a manual
fire — is reachable on every backend, and SQLite lost that race until #1199,
so `test_concurrent_record_fire_on_one_store_does_not_lose_an_increment` runs
against all three.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

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


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def store(
    request: pytest.FixtureRequest, tmp_path, pg_pool: Any
) -> AsyncIterator[ScheduleStore]:
    if request.param == "memory":
        yield InMemoryScheduleStore()
        return
    if request.param == "postgres":
        if pg_pool is None:
            pytest.skip("MAISTRO_TEST_PG_DSN is not set")
        from maistro.scheduling.pg_store import PgScheduleStore

        yield PgScheduleStore(pg_pool)
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
    assert (await store.record_fire("nope", fired_at=NOON, run_id=None, next_due_at=None)) is None


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


async def test_postgres_schedules_are_visible_to_a_second_store(pg_pool: Any) -> None:
    """The property SQLite cannot have: two store handles, one schedule.

    `SqliteScheduleStore` is scoped to "one conductor" by its own docstring.
    A second scheduler replica reading the same row is the whole reason this
    backend exists, so it is asserted rather than assumed.
    """
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    from maistro.scheduling.pg_store import PgScheduleStore

    writer = PgScheduleStore(pg_pool)
    reader = PgScheduleStore(pg_pool)
    schedule = await writer.put(_schedule(name="briefing", cron="0 7 * * 1-5"))
    await writer.record_fire(
        schedule.schedule_id,
        fired_at=NOON,
        run_id="run-abc",
        next_due_at=NOON + timedelta(hours=19),
    )

    seen = await reader.get(schedule.schedule_id)
    assert seen is not None
    assert seen.last_run_id == "run-abc"
    assert seen.next_due_at == NOON + timedelta(hours=19)


async def test_concurrent_record_fire_does_not_lose_an_increment(pg_pool: Any) -> None:
    """Two replicas advancing the same cursor must not both write the same count.

    `runs_so_far` is what `max_runs` exhaustion is computed from, so a lost
    update is not a cosmetic counter error — it is a schedule that fires more
    times than it was configured for. The row lock in `record_fire` is what
    makes this hold; without it both tasks read the same value and write it+1.
    """
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    from maistro.scheduling.pg_store import PgScheduleStore

    store = PgScheduleStore(pg_pool)
    schedule = await store.put(_schedule(name="hourly"))

    replicas = 8
    await asyncio.gather(
        *(
            store.record_fire(
                schedule.schedule_id,
                fired_at=NOON + timedelta(minutes=n),
                run_id=f"run-{n}",
                next_due_at=NOON + timedelta(hours=n + 1),
            )
            for n in range(replicas)
        )
    )

    final = await store.get(schedule.schedule_id)
    assert final is not None
    assert final.runs_so_far == replicas


def test_every_implementation_satisfies_the_protocol() -> None:
    from maistro.scheduling.pg_store import PgScheduleStore

    assert isinstance(InMemoryScheduleStore(), ScheduleStore)
    assert isinstance(PgScheduleStore(None), ScheduleStore)  # type: ignore[arg-type]


# --- the due cursor without a fire (#1199) ------------------------------------


async def test_record_fire_without_a_fired_at_moves_only_the_due_cursor(
    store: ScheduleStore,
) -> None:
    """An evaluation that fired nothing still learned when the next occurrence
    is. Recording that must not stamp `last_fired_at` — that cursor is where
    enumeration resumes, and moving it for a fire that did not happen would
    skip whatever it moved past."""
    schedule = await store.put(
        _schedule(last_fired_at=NOON - timedelta(hours=1), last_run_id="run-0", runs_so_far=1)
    )
    advanced = await store.record_fire(
        schedule.schedule_id,
        fired_at=None,
        run_id=None,
        next_due_at=NOON + timedelta(hours=1),
        fires=0,
    )
    assert advanced is not None
    assert advanced.last_fired_at == NOON - timedelta(hours=1)
    assert advanced.last_run_id == "run-0"
    assert advanced.runs_so_far == 1
    assert advanced.next_due_at == NOON + timedelta(hours=1)
    reloaded = await store.get(schedule.schedule_id)
    assert reloaded is not None
    assert reloaded.last_fired_at == NOON - timedelta(hours=1)
    assert reloaded.next_due_at == NOON + timedelta(hours=1)
    # ...and `due()` reads the recorded cursor: not before it, yes at it.
    assert await store.due(now=NOON) == []
    assert [s.schedule_id for s in await store.due(now=NOON + timedelta(hours=1))] == [
        schedule.schedule_id
    ]


# --- write serialization (#1199) ----------------------------------------------


async def test_concurrent_record_fire_on_one_store_does_not_lose_an_increment(
    store: ScheduleStore,
) -> None:
    """A tick and a manual fire advancing the same cursor at once.

    Both used to be reachable on SQLite as a read, a model copy, and a write
    with nothing between the read and the write — so two callers interleaving
    at the awaits both read `runs_so_far = n` and both wrote `n + 1`. The
    counter is what `max_runs` exhaustion is computed from, and the same lost
    update dropped the other caller's `last_run_id` and `next_due_at`.
    """
    schedule = await store.put(_schedule(name="hourly"))

    callers = 8
    await asyncio.gather(
        *(
            store.record_fire(
                schedule.schedule_id,
                fired_at=NOON + timedelta(minutes=n),
                run_id=f"run-{n}",
                next_due_at=NOON + timedelta(hours=n + 1),
            )
            for n in range(callers)
        )
    )

    final = await store.get(schedule.schedule_id)
    assert final is not None
    assert final.runs_so_far == callers
    # Whichever caller landed last, its cursor is what survived: the counter
    # and the cursors were written by the same caller, not mixed.
    assert final.last_run_id is not None
    winner = int(final.last_run_id.removeprefix("run-"))
    assert final.last_fired_at == NOON + timedelta(minutes=winner)
    assert final.next_due_at == NOON + timedelta(hours=winner + 1)


async def test_concurrent_put_and_record_fire_on_one_sqlite_connection(tmp_path) -> None:
    """Every SQLite writer goes through the one write-critical section.

    `put` and `delete` are locked too, not only `record_fire`: SQLite opens a
    transaction implicitly on a connection's first DML statement, so a `put`
    left mid-flight across an `await` would make `record_fire`'s own `BEGIN
    IMMEDIATE` raise "cannot start a transaction within a transaction" rather
    than merely race with it. Forces the interleaving deterministically: the
    connection's `commit()` is paused after `put`'s INSERT has executed and
    `record_fire` is started inside that window.
    """
    conn = await aiosqlite.connect(tmp_path / "put-vs-fire.db")
    try:
        store = SqliteScheduleStore(conn)
        await store.ensure_schema()
        schedule = await store.put(_schedule(name="hourly"))

        paused_before_commit = asyncio.Event()
        release_commit = asyncio.Event()
        real_commit = conn.commit

        async def commit_after_release() -> None:
            paused_before_commit.set()
            await release_commit.wait()
            await real_commit()

        conn.commit = commit_after_release  # type: ignore[method-assign]
        put_task = asyncio.ensure_future(store.put(_schedule(name="other")))
        try:
            await paused_before_commit.wait()
            fire_task = asyncio.ensure_future(
                store.record_fire(
                    schedule.schedule_id,
                    fired_at=NOON,
                    run_id="run-1",
                    next_due_at=NOON + timedelta(hours=1),
                )
            )
            await asyncio.sleep(0)
            release_commit.set()
            _, advanced = await asyncio.gather(put_task, fire_task)
        finally:
            conn.commit = real_commit  # type: ignore[method-assign]

        assert advanced is not None and advanced.runs_so_far == 1
        reloaded = await store.get(schedule.schedule_id)
        assert reloaded is not None and reloaded.last_run_id == "run-1"
        assert len(await store.list_for_project(workspace_id="w1", project_id="p1")) == 2
    finally:
        await conn.close()


async def test_sqlite_record_fire_from_two_connections_does_not_lose_an_increment(
    tmp_path,
) -> None:
    """The cross-process half: two connections to one file, which is what a
    manual fire from a second process looks like. The in-process lock cannot
    see the other connection; `BEGIN IMMEDIATE` taking SQLite's write lock
    before the read is what makes the second connection wait instead of
    reading a count it is about to overwrite."""
    path = tmp_path / "two-writers.db"
    async with aiosqlite.connect(path) as first, aiosqlite.connect(path) as second:
        store_a = SqliteScheduleStore(first)
        await store_a.ensure_schema()
        store_b = SqliteScheduleStore(second)
        schedule = await store_a.put(_schedule(name="hourly"))

        callers = 6
        await asyncio.gather(
            *(
                (store_a if n % 2 else store_b).record_fire(
                    schedule.schedule_id,
                    fired_at=NOON + timedelta(minutes=n),
                    run_id=f"run-{n}",
                    next_due_at=NOON + timedelta(hours=n + 1),
                )
                for n in range(callers)
            )
        )

        final = await store_a.get(schedule.schedule_id)
        assert final is not None and final.runs_so_far == callers


async def test_a_failed_sqlite_write_rolls_back_and_frees_the_critical_section(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write that raises inside the critical section must leave nothing
    behind: not a half-applied row, and not an open transaction that would
    make the next writer's `BEGIN IMMEDIATE` fail."""
    async with aiosqlite.connect(tmp_path / "rollback.db") as conn:
        store = SqliteScheduleStore(conn)
        await store.ensure_schema()
        schedule = await store.put(_schedule(name="hourly"))

        async def refuse(_schedule: Schedule) -> None:
            raise RuntimeError("disk said no")

        monkeypatch.setattr(store, "_upsert", refuse)
        with pytest.raises(RuntimeError, match="disk said no"):
            await store.record_fire(
                schedule.schedule_id,
                fired_at=NOON,
                run_id="run-1",
                next_due_at=NOON + timedelta(hours=1),
            )
        monkeypatch.undo()

        untouched = await store.get(schedule.schedule_id)
        assert untouched is not None and untouched.runs_so_far == 0
        advanced = await store.record_fire(
            schedule.schedule_id,
            fired_at=NOON,
            run_id="run-1",
            next_due_at=NOON + timedelta(hours=1),
        )
        assert advanced is not None and advanced.runs_so_far == 1
