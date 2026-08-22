"""One suite, three backends, for ADR-086's durable events (#135).

The container used to choose between in-memory and SQLite on "is a SQLite
connection open", so a PostgreSQL deployment — the durable system of record —
got **in-memory** durable events. The event log, the trigger registry and the
invocation history were all lost on restart. "Durable events that are not
durable" is the shape of claim #122 was filed about, one layer up.

`InvocationStore` is the one that carries weight beyond restart safety: it is
what makes event handling idempotent, and in-memory that guarantee held only
within one process and only for one process. A deployment with two workers did
not have it at all. The concurrency section is where that is actually checked.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiosqlite
import pytest

from maistro.events.durable_log import InMemoryEventLog
from maistro.events.invocations import (
    HandlerInvocation,
    InMemoryInvocationStore,
    InvocationStatus,
)
from maistro.events.trigger_store import InMemoryTriggerStore, TriggerDefinition
from maistro.testing.postgres import postgres_dsn


@pytest.fixture
async def sqlite_conn() -> Any:
    conn = await aiosqlite.connect(":memory:")
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def event_log(request: pytest.FixtureRequest, pg_pool: Any, sqlite_conn: Any) -> Any:
    if request.param == "memory":
        yield InMemoryEventLog()
        return
    if request.param == "sqlite":
        from maistro.events.durable_log import SqliteEventLog

        store = SqliteEventLog(sqlite_conn)
        await store.ensure_schema()
        yield store
        return
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    from maistro.events.pg_stores import PgEventLog

    yield PgEventLog(pg_pool)


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def trigger_store(request: pytest.FixtureRequest, pg_pool: Any, sqlite_conn: Any) -> Any:
    if request.param == "memory":
        yield InMemoryTriggerStore()
        return
    if request.param == "sqlite":
        from maistro.events.trigger_store import SqliteTriggerStore

        store = SqliteTriggerStore(sqlite_conn)
        await store.ensure_schema()
        yield store
        return
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    from maistro.events.pg_stores import PgTriggerStore

    yield PgTriggerStore(pg_pool)


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def invocations(request: pytest.FixtureRequest, pg_pool: Any, sqlite_conn: Any) -> Any:
    if request.param == "memory":
        yield InMemoryInvocationStore()
        return
    if request.param == "sqlite":
        from maistro.events.invocations import SqliteInvocationStore

        store = SqliteInvocationStore(sqlite_conn)
        await store.ensure_schema()
        yield store
        return
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    from maistro.events.pg_stores import PgInvocationStore

    yield PgInvocationStore(pg_pool)


# ── event log ─────────────────────────────────────────────────────


async def test_an_appended_event_comes_back(event_log: Any) -> None:
    event = await event_log.append(
        "run.completed", entity_type="run", entity_id="r1", payload={"ok": True}, source="engine"
    )

    reloaded = await event_log.get(event.id)

    assert reloaded is not None
    assert reloaded.event_type == "run.completed"
    assert reloaded.entity_id == "r1"
    assert reloaded.payload == {"ok": True}
    assert reloaded.source == "engine"


async def test_ids_are_monotonic(event_log: Any) -> None:
    """`id` doubles as the replay cursor, so it has to increase or the loop
    either re-reads or skips."""
    ids = [(await event_log.append(f"e{i}")).id for i in range(5)]

    assert ids == sorted(ids)
    assert len(set(ids)) == 5


async def test_a_nested_payload_round_trips(event_log: Any) -> None:
    """JSONB on PostgreSQL, encoded text on SQLite, a plain dict in memory."""
    payload = {"nested": {"list": [1, 2, {"deep": True}]}, "null": None, "text": "ü"}

    event = await event_log.append("shaped", payload=payload)

    reloaded = await event_log.get(event.id)
    assert reloaded is not None
    assert reloaded.payload == payload


async def test_an_empty_payload_is_a_dict_not_none(event_log: Any) -> None:
    event = await event_log.append("bare")

    reloaded = await event_log.get(event.id)
    assert reloaded is not None
    assert reloaded.payload == {}


async def test_an_unknown_event_is_none(event_log: Any) -> None:
    assert await event_log.get(999_999) is None


async def test_query_filters_by_type(event_log: Any) -> None:
    await event_log.append("wanted")
    await event_log.append("unwanted")
    await event_log.append("wanted")

    found = await event_log.query(event_type="wanted")

    assert [e.event_type for e in found] == ["wanted", "wanted"]


async def test_query_paginates_by_cursor(event_log: Any) -> None:
    ids = [(await event_log.append("paged")).id for _ in range(5)]

    first = await event_log.query(limit=2)
    second = await event_log.query(after_id=first[-1].id, limit=2)

    assert [e.id for e in first] == ids[:2]
    assert [e.id for e in second] == ids[2:4]


async def test_query_returns_ascending_by_id(event_log: Any) -> None:
    for _ in range(4):
        await event_log.append("ordered")

    found = await event_log.query()

    assert [e.id for e in found] == sorted(e.id for e in found)


async def test_query_with_no_matches_is_empty(event_log: Any) -> None:
    await event_log.append("something")

    assert await event_log.query(event_type="nothing-like-this") == []


# ── triggers ──────────────────────────────────────────────────────


def _trigger(**overrides: Any) -> TriggerDefinition:
    fields: dict[str, Any] = {
        "trigger_id": "t1",
        "name": "notify",
        "event_pattern": "run.*",
        "handler_url": "https://example.test/hook",
        "enabled": True,
    }
    fields.update(overrides)
    return TriggerDefinition(**fields)


async def test_a_trigger_round_trips(trigger_store: Any) -> None:
    await trigger_store.add(_trigger())

    reloaded = await trigger_store.get("t1")

    assert reloaded is not None
    assert reloaded.event_pattern == "run.*"
    assert reloaded.handler_url == "https://example.test/hook"
    assert reloaded.enabled is True


async def test_adding_the_same_id_replaces_it(trigger_store: Any) -> None:
    await trigger_store.add(_trigger())
    await trigger_store.add(_trigger(handler_url="https://example.test/other"))

    assert len(await trigger_store.list_triggers()) == 1
    reloaded = await trigger_store.get("t1")
    assert reloaded is not None
    assert reloaded.handler_url == "https://example.test/other"


async def test_matching_uses_glob_semantics(trigger_store: Any) -> None:
    """The pattern match happens in Python on every backend, because glob is
    not expressible in portable SQL — so all three must agree on it."""
    await trigger_store.add(_trigger(trigger_id="t1", event_pattern="run.*"))
    await trigger_store.add(_trigger(trigger_id="t2", event_pattern="task.*"))

    matched = await trigger_store.get_matching("run.completed")

    assert [t.trigger_id for t in matched] == ["t1"]


async def test_a_disabled_trigger_does_not_match(trigger_store: Any) -> None:
    await trigger_store.add(_trigger(enabled=False))

    assert await trigger_store.get_matching("run.completed") == []


async def test_set_enabled_toggles_matching(trigger_store: Any) -> None:
    await trigger_store.add(_trigger(enabled=False))

    await trigger_store.set_enabled("t1", True)

    assert len(await trigger_store.get_matching("run.completed")) == 1


async def test_removing_a_trigger_removes_it(trigger_store: Any) -> None:
    await trigger_store.add(_trigger())

    await trigger_store.remove("t1")

    assert await trigger_store.get("t1") is None
    assert await trigger_store.list_triggers() == []


async def test_removing_an_unknown_trigger_is_not_an_error(trigger_store: Any) -> None:
    await trigger_store.remove("never-added")


async def test_an_unknown_trigger_is_none(trigger_store: Any) -> None:
    assert await trigger_store.get("never-added") is None


# ── invocations: the idempotency guarantee ────────────────────────


async def test_get_or_create_makes_one_pending_invocation(invocations: Any) -> None:
    invocation = await invocations.get_or_create("t1", 1)

    assert invocation.status is InvocationStatus.PENDING
    assert invocation.attempts == 0
    assert invocation.is_terminal is False


async def test_get_or_create_is_idempotent(invocations: Any) -> None:
    """Replay after a crash must find the existing row, not start a second
    handler run for the same event."""
    first = await invocations.get_or_create("t1", 1)
    second = await invocations.get_or_create("t1", 1)

    assert (second.trigger_id, second.event_id) == (first.trigger_id, first.event_id)
    assert second.created_at == first.created_at
    assert len(await invocations.list_for_event(1)) == 1


async def test_get_or_create_does_not_reset_progress(invocations: Any) -> None:
    """The sharpest version: a redelivery after two failed attempts must not
    hand back a fresh pending invocation and lose the retry count."""
    await invocations.get_or_create("t1", 1)
    await invocations.save(
        HandlerInvocation(
            trigger_id="t1",
            event_id=1,
            status=InvocationStatus.RETRYING,
            attempts=2,
            last_error="boom",
        )
    )

    again = await invocations.get_or_create("t1", 1)

    assert again.attempts == 2
    assert again.status is InvocationStatus.RETRYING
    assert again.last_error == "boom"


async def test_different_triggers_for_one_event_are_separate(invocations: Any) -> None:
    await invocations.get_or_create("t1", 1)
    await invocations.get_or_create("t2", 1)

    assert len(await invocations.list_for_event(1)) == 2


async def test_the_same_trigger_for_different_events_is_separate(invocations: Any) -> None:
    await invocations.get_or_create("t1", 1)
    await invocations.get_or_create("t1", 2)

    assert len(await invocations.list_for_event(1)) == 1
    assert len(await invocations.list_for_event(2)) == 1


async def test_save_persists_terminal_state(invocations: Any) -> None:
    await invocations.get_or_create("t1", 1)

    await invocations.save(
        HandlerInvocation(
            trigger_id="t1",
            event_id=1,
            status=InvocationStatus.FAILED,
            attempts=3,
            last_error="gave up",
        )
    )

    reloaded = await invocations.get("t1", 1)
    assert reloaded is not None
    assert reloaded.status is InvocationStatus.FAILED
    assert reloaded.is_terminal is True
    assert reloaded.last_error == "gave up"


async def test_an_unknown_invocation_is_none(invocations: Any) -> None:
    assert await invocations.get("never", 999) is None


async def test_list_for_an_event_with_none_is_empty(invocations: Any) -> None:
    assert await invocations.list_for_event(999) == []


# ── concurrency: what in-memory could not offer across processes ──


async def test_concurrent_workers_produce_exactly_one_invocation(invocations: Any) -> None:
    """Eight workers handed the same event. One invocation, or the handler runs
    eight times for one event — which is what "idempotent event handling" is
    supposed to prevent."""
    results = await asyncio.gather(
        *(invocations.get_or_create("t1", 1) for _ in range(8)),
        return_exceptions=True,
    )

    failures = [r for r in results if isinstance(r, BaseException)]
    assert failures == [], f"a racing worker must not crash: {failures}"
    assert len({r.created_at for r in results}) == 1, "all must see one invocation"
    assert len(await invocations.list_for_event(1)) == 1


async def test_concurrent_appends_get_distinct_ids(event_log: Any) -> None:
    """Two appends must not share a replay cursor."""
    results = await asyncio.gather(*(event_log.append("raced") for _ in range(8)))

    assert len({e.id for e in results}) == 8


def test_postgres_is_covered_when_configured() -> None:
    if not postgres_dsn():
        pytest.skip("no PostgreSQL configured; the parametrized cases skip by design")
    pytest.importorskip("asyncpg")
