"""One suite over all three durable-event backends (#135).

ADR-086's stores existed in-memory and on SQLite. The container selects on
`db_pool is not None` where `db_pool` is a *SQLite* connection, so a deployment
on PostgreSQL — the durable system of record — got in-memory durable events:
event log, trigger registry and invocation history all lost on restart.

The consequence that outlives a restart is **idempotency**. `InvocationStore` is
how a redelivered event is recognised as already handled, and in-memory that
holds within one process, for one process. Multi-worker deployments never had
it — and multi-worker is the only reason to reach for PostgreSQL here.

So `TestIdempotencyUnderConcurrency` is the point of this file: two workers
racing on the same `(trigger_id, event_id)` must produce **one** invocation.
SQLite never had to answer that question; PostgreSQL does, and the answer is a
composite primary key with `ON CONFLICT DO NOTHING` rather than a read-then-write
with a window in it.

The PostgreSQL leg skips without `MAISTRO_TEST_DATABASE_URL`. A skipped leg is
untested, not passing — which is how the gap this file closes went unnoticed.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from maistro.events.durable_log import InMemoryEventLog, SqliteEventLog
from maistro.events.invocations import (
    HandlerInvocation,
    InMemoryInvocationStore,
    InvocationStatus,
    SqliteInvocationStore,
)
from maistro.events.trigger_store import (
    InMemoryTriggerStore,
    SqliteTriggerStore,
    TriggerDefinition,
)

DATABASE_URL = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")
BACKENDS = ["memory", "sqlite", "postgres"]


def _require_postgres() -> str:
    """The URL, or a skip — unless the caller declared a server is guaranteed.

    `MAISTRO_REQUIRE_PG_LEGS` is set by the `durable-events` CI job, which owns
    a postgres service container. There, "no URL" means the job is misconfigured,
    and skipping would leave it green with the whole point of #135 unexercised —
    a skipped leg is untested, not passing. Everywhere else (a laptop, the plain
    `test` job) skipping is the right answer.
    """
    if DATABASE_URL:
        return DATABASE_URL
    if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
        msg = (
            "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_DATABASE_URL is empty: "
            "the PostgreSQL leg cannot run and must not be silently skipped"
        )
        raise RuntimeError(msg)
    pytest.skip("MAISTRO_TEST_DATABASE_URL is unset; the PostgreSQL leg needs a real server")


async def _sqlite_conn():
    import aiosqlite

    return await aiosqlite.connect(":memory:")


async def _pg_pool():
    url = _require_postgres()
    import asyncpg

    from maistro.events.pg_stores import ensure_event_schema

    pool = await asyncpg.create_pool(url, min_size=1, max_size=8)
    await ensure_event_schema(pool)
    # Truncate rather than drop: the schema is created once and each test needs
    # empty tables, without racing CREATE TABLE IF NOT EXISTS across the pool.
    await pool.execute("TRUNCATE handler_invocations, trigger_definitions, event_log")
    return pool


@pytest.fixture(params=BACKENDS)
async def event_log(request):
    if request.param == "memory":
        return InMemoryEventLog()
    if request.param == "sqlite":
        store = SqliteEventLog(await _sqlite_conn())
        await store.ensure_schema()
        return store
    from maistro.events.pg_stores import PgEventLog

    return PgEventLog(await _pg_pool())


@pytest.fixture(params=BACKENDS)
async def trigger_store(request):
    if request.param == "memory":
        return InMemoryTriggerStore()
    if request.param == "sqlite":
        store = SqliteTriggerStore(await _sqlite_conn())
        await store.ensure_schema()
        return store
    from maistro.events.pg_stores import PgTriggerStore

    return PgTriggerStore(await _pg_pool())


@pytest.fixture(params=BACKENDS)
async def invocations(request):
    if request.param == "memory":
        return InMemoryInvocationStore()
    if request.param == "sqlite":
        store = SqliteInvocationStore(await _sqlite_conn())
        await store.ensure_schema()
        return store
    from maistro.events.pg_stores import PgInvocationStore

    return PgInvocationStore(await _pg_pool())


class TestEventLog:
    async def test_append_returns_the_stored_event(self, event_log):
        event = await event_log.append(
            "task.created",
            entity_type="task",
            entity_id="t1",
            payload={"n": 1, "s": "x"},
            source="api",
        )
        assert event.id > 0
        assert event.event_type == "task.created"
        assert event.entity_type == "task"
        assert event.entity_id == "t1"
        assert event.payload == {"n": 1, "s": "x"}
        assert event.source == "api"

    async def test_get_round_trips_the_payload(self, event_log):
        """JSON, not repr. A backend storing the dict's `str()` would pass an
        equality check on simple values and lose types on the next one."""
        payload = {"n": 1, "f": 1.5, "b": True, "none": None, "list": [1, "two"], "d": {"k": "v"}}
        written = await event_log.append("e", payload=payload)
        read = await event_log.get(written.id)
        assert read is not None
        assert read.payload == payload

    async def test_get_returns_none_for_an_unknown_id(self, event_log):
        assert await event_log.get(999_999) is None

    async def test_ids_increase(self, event_log):
        first = await event_log.append("a")
        second = await event_log.append("b")
        assert second.id > first.id

    async def test_query_returns_events_after_a_cursor_in_order(self, event_log):
        ids = [(await event_log.append(f"e{i}")).id for i in range(5)]
        page = await event_log.query(after_id=ids[1])
        assert [e.id for e in page] == ids[2:]

    async def test_query_filters_by_event_type(self, event_log):
        await event_log.append("task.created")
        await event_log.append("task.done")
        await event_log.append("task.created")
        assert len(await event_log.query(event_type="task.created")) == 2

    async def test_query_respects_the_limit(self, event_log):
        for i in range(5):
            await event_log.append(f"e{i}")
        assert len(await event_log.query(limit=2)) == 2

    async def test_query_bounds_by_time(self, event_log):
        early = await event_log.append("a")
        await asyncio.sleep(0.01)
        late = await event_log.append("b")
        assert [e.id for e in await event_log.query(since=late.created_at)] == [late.id]
        assert [e.id for e in await event_log.query(until=early.created_at)] == [early.id]

    async def test_since_and_until_are_not_confused_when_equal(self, event_log):
        """Both bounds set to the same instant must select that instant only.

        The PostgreSQL builder derived its operator by identity (`value is
        since`); CPython interns equal floats, so `until` was emitted as `>=`
        and the upper bound silently became a second lower bound.
        """
        first = await event_log.append("a")
        await asyncio.sleep(0.01)
        await event_log.append("b")
        found = await event_log.query(since=first.created_at, until=first.created_at)
        assert [e.id for e in found] == [first.id]


class TestTriggerStore:
    async def test_add_then_get_round_trips(self, trigger_store):
        trigger = TriggerDefinition(
            trigger_id="t1", name="n", event_pattern="task.*", handler_url="http://h", enabled=True
        )
        await trigger_store.add(trigger)
        read = await trigger_store.get("t1")
        assert read is not None
        assert (read.name, read.event_pattern, read.handler_url, read.enabled) == (
            "n",
            "task.*",
            "http://h",
            True,
        )

    async def test_get_returns_none_for_an_unknown_id(self, trigger_store):
        assert await trigger_store.get("nope") is None

    async def test_add_upserts_rather_than_duplicating(self, trigger_store):
        await trigger_store.add(TriggerDefinition(trigger_id="t1", name="first"))
        await trigger_store.add(TriggerDefinition(trigger_id="t1", name="second"))
        assert len(await trigger_store.list_triggers()) == 1
        assert (await trigger_store.get("t1")).name == "second"

    async def test_remove_deletes(self, trigger_store):
        await trigger_store.add(TriggerDefinition(trigger_id="t1"))
        await trigger_store.remove("t1")
        assert await trigger_store.get("t1") is None

    async def test_removing_an_absent_trigger_does_not_raise(self, trigger_store):
        await trigger_store.remove("never-existed")

    async def test_get_matching_uses_segment_globs(self, trigger_store):
        """Matching is per-segment: `task.*` matches `task.created` and not
        `agent.task.created`. Filtered in Python on every backend, because SQL
        `LIKE` cannot express it — and a backend that approximated it would make
        "which triggers fire" a per-deployment question."""
        await trigger_store.add(TriggerDefinition(trigger_id="t1", event_pattern="task.*"))
        await trigger_store.add(TriggerDefinition(trigger_id="t2", event_pattern="agent.*"))
        matched = await trigger_store.get_matching("task.created")
        assert [t.trigger_id for t in matched] == ["t1"]
        assert await trigger_store.get_matching("agent.task.created") == []

    async def test_disabled_triggers_do_not_match(self, trigger_store):
        await trigger_store.add(
            TriggerDefinition(trigger_id="t1", event_pattern="task.*", enabled=False)
        )
        assert await trigger_store.get_matching("task.created") == []

    async def test_set_enabled_toggles_matching(self, trigger_store):
        await trigger_store.add(
            TriggerDefinition(trigger_id="t1", event_pattern="task.*", enabled=False)
        )
        await trigger_store.set_enabled("t1", True)
        assert len(await trigger_store.get_matching("task.created")) == 1
        await trigger_store.set_enabled("t1", False)
        assert await trigger_store.get_matching("task.created") == []


class TestInvocationStore:
    async def test_get_or_create_creates_a_pending_invocation(self, invocations):
        invocation = await invocations.get_or_create("t1", 1)
        assert invocation.trigger_id == "t1"
        assert invocation.event_id == 1
        assert invocation.status is InvocationStatus.PENDING
        assert invocation.attempts == 0

    async def test_get_or_create_is_idempotent(self, invocations):
        """The sequential case. The concurrent one is below, and is the one
        SQLite never had to answer."""
        first = await invocations.get_or_create("t1", 1)
        second = await invocations.get_or_create("t1", 1)
        assert second.created_at == first.created_at
        assert len(await invocations.list_for_event(1)) == 1

    async def test_get_returns_none_before_creation(self, invocations):
        assert await invocations.get("t1", 1) is None

    async def test_save_updates_status_and_attempts(self, invocations):
        invocation = await invocations.get_or_create("t1", 1)
        invocation.status = InvocationStatus.FAILED
        invocation.attempts = 3
        invocation.last_error = "boom"
        await invocations.save(invocation)
        read = await invocations.get("t1", 1)
        assert read is not None
        assert read.status is InvocationStatus.FAILED
        assert read.attempts == 3
        assert read.last_error == "boom"
        assert read.is_terminal is True

    async def test_save_does_not_duplicate_the_row(self, invocations):
        await invocations.get_or_create("t1", 1)
        await invocations.save(HandlerInvocation(trigger_id="t1", event_id=1, attempts=9))
        assert len(await invocations.list_for_event(1)) == 1

    async def test_different_triggers_on_one_event_are_separate(self, invocations):
        await invocations.get_or_create("t1", 1)
        await invocations.get_or_create("t2", 1)
        assert len(await invocations.list_for_event(1)) == 2

    async def test_the_same_trigger_on_different_events_is_separate(self, invocations):
        await invocations.get_or_create("t1", 1)
        await invocations.get_or_create("t1", 2)
        assert len(await invocations.list_for_event(1)) == 1
        assert len(await invocations.list_for_event(2)) == 1


class TestDispatchIsLeasedToOneWorker:
    """The composite key deduplicates rows. It does not deduplicate *dispatch*
    (Codex review, #181).

    `get_or_create` hands every racing worker the same non-terminal row, and
    `process_events` reads "not terminal" as permission to call the handler — so
    one event fired the side effect once per worker while the bookkeeping showed
    a single tidy invocation. ADR-086 says a handler is invoked "at most once
    successfully per event"; one row and two handler calls is not that.
    """

    async def test_only_one_of_many_racing_claims_succeeds(self, invocations):
        claims = await asyncio.gather(*(invocations.claim("t1", 42) for _ in range(16)))

        winners = [c for c in claims if c is not None]
        assert len(winners) == 1, f"{len(winners)} workers would have called the handler"
        assert len(await invocations.list_for_event(42)) == 1

    async def test_the_loser_gets_none_rather_than_a_dispatchable_row(self, invocations):
        """The distinction the bug turned on: a non-terminal row reads as
        permission to dispatch, so the loser must not receive one."""
        assert await invocations.claim("t1", 1) is not None
        assert await invocations.claim("t1", 1) is None

    async def test_a_terminal_invocation_is_never_reclaimed(self, invocations):
        invocation = await invocations.claim("t1", 1)
        assert invocation is not None
        invocation.status = InvocationStatus.SUCCESS
        invocation.lease_expires_at = 0.0
        await invocations.save(invocation)

        assert await invocations.claim("t1", 1) is None

    async def test_a_released_lease_can_be_reclaimed(self, invocations):
        """The normal retry path: a handler failed, the worker released the
        lease, the next tick must be able to pick the event up again. Without
        this the retry waits out the whole lease window instead."""
        first = await invocations.claim("t1", 1)
        assert first is not None
        first.status = InvocationStatus.RETRYING
        first.lease_expires_at = 0.0
        await invocations.save(first)

        second = await invocations.claim("t1", 1)
        assert second is not None
        assert second.attempts == 2

    async def test_an_expired_lease_is_reclaimable(self, invocations):
        """A worker killed between claiming and finishing releases nothing. The
        lease has to lapse on its own, or one dead process strands the event
        forever — trading a double-dispatch bug for a stuck-queue one."""
        assert await invocations.claim("t1", 1, lease_seconds=-1.0) is not None

        reclaimed = await invocations.claim("t1", 1)
        assert reclaimed is not None
        assert reclaimed.attempts == 2

    async def test_claiming_counts_attempts_so_retries_still_converge(self, invocations):
        """`process_events` used to increment `attempts` itself. Now the claim
        does, inside the same statement — otherwise a handler that keeps dying
        is retried forever by whichever worker wins each round."""
        for expected in (1, 2, 3):
            invocation = await invocations.claim("t1", 1, lease_seconds=-1.0)
            assert invocation is not None
            assert invocation.attempts == expected

    async def test_claims_on_different_keys_do_not_block_each_other(self, invocations):
        assert await invocations.claim("t1", 1) is not None
        assert await invocations.claim("t2", 1) is not None
        assert await invocations.claim("t1", 2) is not None


class TestIdempotencyUnderConcurrency:
    """The substance of #135: one invocation per redelivered event, per trigger.

    In-memory holds this within one process. SQLite holds it within one
    connection. Only PostgreSQL is asked the real question, because it is the
    only backend a second worker can reach — and multi-worker is the only reason
    to choose it here.
    """

    async def test_concurrent_get_or_create_produces_one_invocation(self, invocations):
        results = await asyncio.gather(*(invocations.get_or_create("t1", 42) for _ in range(16)))
        stored = await invocations.list_for_event(42)
        assert len(stored) == 1, f"{len(stored)} invocations for one (trigger, event)"
        # Every caller must see the *same* row, not merely "a" row: a caller
        # holding a different `created_at` would treat its own copy as
        # authoritative and re-run the handler.
        assert len({r.created_at for r in results}) == 1
        assert len({(r.trigger_id, r.event_id) for r in results}) == 1

    async def test_concurrent_creates_across_triggers_do_not_collide(self, invocations):
        await asyncio.gather(
            *(invocations.get_or_create(f"t{i}", 7) for i in range(8) for _ in range(4))
        )
        assert len(await invocations.list_for_event(7)) == 8

    async def test_a_redelivered_event_after_completion_is_still_one_row(self, invocations):
        """Redelivery does not always arrive while the first attempt is in
        flight. A completed invocation must not be reset to pending by a late
        duplicate — that would re-run a handler that already succeeded."""
        invocation = await invocations.get_or_create("t1", 1)
        invocation.status = InvocationStatus.SUCCESS
        await invocations.save(invocation)
        again = await invocations.get_or_create("t1", 1)
        assert again.status is InvocationStatus.SUCCESS
        assert len(await invocations.list_for_event(1)) == 1
