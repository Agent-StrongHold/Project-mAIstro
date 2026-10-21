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
from typing import ClassVar

import aiosqlite
import pytest

from maistro.events.consumer_cursor import InMemoryConsumerCursorStore, SqliteConsumerCursorStore
from maistro.events.durable_log import InMemoryEventLog, LoggedEvent, SqliteEventLog
from maistro.events.invocations import (
    DeliveryAlreadyStarted,
    DeliveryAttemptLimitReached,
    DeliveryDisposition,
    DeliveryIdentity,
    DeliveryIdentityMismatch,
    HandlerCallOutcome,
    HandlerInvocation,
    InMemoryInvocationStore,
    InvocationStatus,
    ReplaySafety,
    SqliteInvocationStore,
    request_digest_v1,
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
    return await aiosqlite.connect(":memory:")


async def _pg_pool():
    url = _require_postgres()
    import asyncpg

    from maistro.events.pg_stores import ensure_event_schema

    pool = await asyncpg.create_pool(url, min_size=1, max_size=8)
    await ensure_event_schema(pool)
    # Truncate rather than drop: the schema is created once and each test needs
    # empty tables, without racing CREATE TABLE IF NOT EXISTS across the pool.
    await pool.execute(
        "TRUNCATE handler_invocations, trigger_definitions, event_log, event_replay_cursors"
    )
    return pool


@pytest.fixture(autouse=True)
def _fail_on_leaked_aiosqlite_connections(monkeypatch):
    """Regression guard for #1077: every `aiosqlite` connection opened by this
    module's fixtures must be closed by that fixture's own teardown, while the
    test's event loop is still alive.

    This fixture is set up before the store fixtures (autouse) and therefore
    torn down after them, so any connection still open here was leaked by its
    fixture — exactly the failure mode that used to surface much later as GC
    ResourceWarnings and `Event loop is closed` callbacks in CI teardown,
    attributed to whichever unrelated test happened to trigger the collection.

    Ownership order is explicit: the sqlite-backed fixture that opens the
    connection closes it; this guard only *observes*, after all of them have
    finalized.

    Closed-state is probed through aiosqlite internals because `Connection`
    has no public accessor:
      - `_connection is not None` → the sqlite handle is still held (open)
      - `_running` with a released handle → the background thread was started
        but the connection never awaited to open nor closed (leaked at birth)
    A cleanly closed connection has `_connection is None` and `_running` False.
    """

    created: list[aiosqlite.Connection] = []
    real_connect = aiosqlite.connect

    def tracking_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        created.append(conn)
        return conn

    monkeypatch.setattr(aiosqlite, "connect", tracking_connect)
    yield
    leaked = [conn for conn in created if conn._connection is not None or conn._running]
    assert not leaked, (
        f"{len(leaked)} of {len(created)} aiosqlite connection(s) outlived their "
        "fixture teardown (#1077); close the connection where it is owned — the "
        "fixture — not via GC finalizers"
    )


# Fixture ownership (#1077): the sqlite legs of these fixtures open a real
# `aiosqlite` connection and the postgres legs open a real asyncpg pool, so
# each fixture that opens a resource closes it in its own teardown — an async
# generator with `try/finally`, not a bare `return`. Returning a live store
# used to leak one connection per parametrized instantiation; the connection's
# background thread kept running into the loop's close and surfaced much later
# as `Event loop is closed` teardown noise on CI. The autouse guard below
# turns any regression back into a deterministic failure at the fixture's own
# boundary.
@pytest.fixture(params=BACKENDS)
async def event_log(request):
    if request.param == "memory":
        yield InMemoryEventLog()
    elif request.param == "sqlite":
        conn = await _sqlite_conn()
        try:
            store = SqliteEventLog(conn)
            await store.ensure_schema()
            yield store
        finally:
            await conn.close()
    else:
        from maistro.events.pg_stores import PgEventLog

        pool = await _pg_pool()
        try:
            yield PgEventLog(pool)
        finally:
            await pool.close()


@pytest.fixture(params=BACKENDS)
async def trigger_store(request):
    if request.param == "memory":
        yield InMemoryTriggerStore()
    elif request.param == "sqlite":
        conn = await _sqlite_conn()
        try:
            store = SqliteTriggerStore(conn)
            await store.ensure_schema()
            yield store
        finally:
            await conn.close()
    else:
        from maistro.events.pg_stores import PgTriggerStore

        pool = await _pg_pool()
        try:
            yield PgTriggerStore(pool)
        finally:
            await pool.close()


@pytest.fixture(params=BACKENDS)
async def invocations(request):
    if request.param == "memory":
        yield InMemoryInvocationStore()
    elif request.param == "sqlite":
        conn = await _sqlite_conn()
        try:
            store = SqliteInvocationStore(conn)
            await store.ensure_schema()
            yield store
        finally:
            await conn.close()
    else:
        from maistro.events.pg_stores import PgInvocationStore

        pool = await _pg_pool()
        try:
            yield PgInvocationStore(pool)
        finally:
            await pool.close()


@pytest.fixture(params=BACKENDS)
async def cursor_store(request):
    if request.param == "memory":
        yield InMemoryConsumerCursorStore()
    elif request.param == "sqlite":
        conn = await _sqlite_conn()
        try:
            store = SqliteConsumerCursorStore(conn)
            await store.ensure_schema()
            yield store
        finally:
            await conn.close()
    else:
        from maistro.events.pg_stores import PgConsumerCursorStore

        pool = await _pg_pool()
        try:
            await pool.execute("TRUNCATE consumer_cursors")
            yield PgConsumerCursorStore(pool)
        finally:
            await pool.close()


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

    async def test_append_rejects_non_strict_json_payloads(self, event_log):
        """NaN would persist but raise in `request_digest_v1` (allow_nan=False)
        before the receipt claim — no receipt could ever settle, so the cursor
        would wedge on that event forever. Append is the gate, for non-finite
        floats and for values `json` cannot encode at all."""
        with pytest.raises(ValueError, match="strictly JSON-encodable"):
            await event_log.append("e", payload={"score": float("nan")})
        with pytest.raises(ValueError, match="strictly JSON-encodable"):
            await event_log.append("e", payload={"bad": [float("inf")]})
        with pytest.raises(ValueError, match="strictly JSON-encodable"):
            await event_log.append("e", payload={"s": {1, 2}})

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


class TestReplayCursor:
    """Durable replay acknowledgements (#836/#1163) on every backend.

    A cursor that lives only in process memory cannot survive the restart it
    exists for, so the acknowledgement is a store concern — asserted here for
    the PostgreSQL leg exactly as for memory and SQLite.
    """

    async def test_acknowledgement_is_monotonic(self, event_log):
        assert await event_log.get_replay_cursor("reactor") == 0
        assert await event_log.acknowledge_replay("reactor", 4) == 4
        assert await event_log.acknowledge_replay("reactor", 2) == 4
        assert await event_log.get_replay_cursor("reactor") == 4

    async def test_negative_acknowledgement_is_rejected(self, event_log):
        with pytest.raises(ValueError, match="non-negative"):
            await event_log.acknowledge_replay("reactor", -1)


async def test_pg_replay_cursor_survives_a_pool_restart():
    """The PostgreSQL cursor is durable, not pool-lifetime state.

    Mirrors the SQLite restart test in `test_durable_log.py`: a new pool (a
    restarted worker) must resume from the acknowledged position instead of
    replaying settled events as if they were new.
    """
    import asyncpg

    from maistro.events.pg_stores import PgEventLog, ensure_event_schema

    url = _require_postgres()
    first_pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    try:
        await ensure_event_schema(first_pool)
        await first_pool.execute("TRUNCATE event_log, event_replay_cursors")
        first = PgEventLog(first_pool)
        event = await first.append("task.created")
        assert await first.acknowledge_replay("reactor", event.id) == event.id
    finally:
        await first_pool.close()

    second_pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    try:
        restarted = PgEventLog(second_pool)
        assert await restarted.get_replay_cursor("reactor") == event.id
    finally:
        await second_pool.close()


class TestTriggerStore:
    async def test_add_then_get_round_trips(self, trigger_store):
        trigger = TriggerDefinition(
            trigger_id="t1",
            name="n",
            event_pattern="task.*",
            handler_url="http://h",
            enabled=True,
            replay_safety=ReplaySafety.IDEMPOTENT,
            contract_ref="contract-v1",
        )
        await trigger_store.add(trigger)
        read = await trigger_store.get("t1")
        assert read is not None
        assert (
            read.name,
            read.event_pattern,
            read.handler_url,
            read.enabled,
            read.replay_safety,
            read.contract_ref,
        ) == (
            "n",
            "task.*",
            "http://h",
            True,
            ReplaySafety.IDEMPOTENT,
            "contract-v1",
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


def _identity(
    url: str = "http://h",
    digest: str = "v1:d",
    safety: ReplaySafety = ReplaySafety.IDEMPOTENT,
    ref: str = "contract-v1",
) -> DeliveryIdentity:
    return DeliveryIdentity(
        handler_url=url, request_digest=digest, replay_safety=safety, contract_ref=ref
    )


async def _claim_and_begin(invocations, identity, *, trigger_id="t1", event_id=1):
    claimed = await invocations.claim(trigger_id, event_id, delivery=identity)
    assert claimed is not None
    begun = await invocations.begin_dispatch(
        trigger_id,
        event_id,
        claim_token=claimed.claim_token,
        expected_revision=claimed.revision,
        delivery=identity,
    )
    assert begun is not None
    return claimed, begun


class TestDeliveryReceiptContract:
    """The #1060 §6 conformance body over memory, SQLite and PostgreSQL.

    One contract, three backends: detached snapshots, one key winner, exact
    immutable context, the begin/send cap including kill loops, stale CAS
    never sends or settles, a delayed old sender after takeover, the UNKNOWN
    oracle for inherited uncertainty, and fail-closed legacy migration.
    """

    async def test_reads_are_detached_snapshots(self, invocations):
        identity = _identity()
        claimed = await invocations.claim("t1", 1, delivery=identity)
        assert claimed is not None
        claimed.status = InvocationStatus.SUCCESS  # mutate the snapshot...
        reread = await invocations.get("t1", 1)
        assert reread is not None
        assert reread.status is InvocationStatus.PENDING  # ...the store kept its truth

    async def test_one_claim_wins_and_allocates_exactly_one_key(self, invocations):
        identity = _identity()
        claims = await asyncio.gather(
            *(invocations.claim("t1", 42, delivery=identity) for _ in range(16))
        )
        winners = [c for c in claims if c is not None]
        assert len(winners) == 1, f"{len(winners)} workers would have sent"
        assert winners[0].delivery_key is not None
        assert len(await invocations.list_for_event(42)) == 1
        # The loser gets None, never a dispatchable row.
        assert await invocations.claim("t1", 42, delivery=identity) is None

    async def test_a_live_lease_or_settled_row_refuses_the_claim(self, invocations):
        identity = _identity()
        _, begun = await _claim_and_begin(invocations, identity)
        # Live lease: refused (covered above too, but this pins the in-flight
        # marker case, where a crash has left the receipt mid-dispatch).
        assert await invocations.claim("t1", 1, delivery=identity) is None
        settled = await invocations.settle(
            "t1",
            1,
            claim_token=begun.claim_token,
            expected_revision=begun.revision,
            status=InvocationStatus.SUCCESS,
            outcome=HandlerCallOutcome(DeliveryDisposition.ACKNOWLEDGED),
        )
        assert settled is not None
        # Cursor-settled: refused forever after.
        assert await invocations.claim("t1", 1, delivery=identity) is None

    async def test_the_prepared_identity_is_immutable_across_claims(self, invocations):
        """A takeover with a different destination keeps the frozen context —
        the owning processor settles the mismatch visibly, without HTTP."""
        first = await invocations.claim("t1", 1, delivery=_identity())
        assert first is not None
        await invocations.settle(
            "t1",
            1,
            claim_token=first.claim_token,
            expected_revision=first.revision,
            status=InvocationStatus.RETRYING,
            outcome=HandlerCallOutcome(DeliveryDisposition.NOT_APPLIED, "pre_send_refusal"),
        )
        changed = _identity(url="http://other", digest="v1:other", ref="contract-v2")
        reclaimed = await invocations.claim("t1", 1, delivery=changed)
        assert reclaimed is not None
        assert reclaimed.delivery_key == first.delivery_key
        assert (reclaimed.handler_url, reclaimed.request_digest, reclaimed.contract_ref) == (
            "http://h",
            "v1:d",
            "contract-v1",
        )
        # begin with the changed identity is an identity mismatch, not a send.
        with pytest.raises(DeliveryIdentityMismatch):
            await invocations.begin_dispatch(
                "t1",
                1,
                claim_token=reclaimed.claim_token,
                expected_revision=reclaimed.revision,
                delivery=changed,
            )

    async def test_begin_consumes_the_sole_send_permission(self, invocations):
        identity = _identity()
        claimed = await invocations.claim("t1", 1, delivery=identity)
        assert claimed is not None
        begun = await invocations.begin_dispatch(
            "t1",
            1,
            claim_token=claimed.claim_token,
            expected_revision=claimed.revision,
            delivery=identity,
        )
        assert begun is not None
        assert begun.attempts == 1
        assert begun.dispatch_started_at is not None
        assert begun.revision == claimed.revision + 1
        # A second begin for one claim is refused.
        with pytest.raises(DeliveryAlreadyStarted):
            await invocations.begin_dispatch(
                "t1",
                1,
                claim_token=claimed.claim_token,
                expected_revision=begun.revision,
                delivery=identity,
            )

    async def test_the_cap_survives_repeated_death_and_reclaim(self, invocations):
        """Kill loops cannot buy a fourth send: begin, not claim, spends budget."""
        identity = _identity()
        for expected in (1, 2):
            claimed, begun = await _claim_and_begin(invocations, identity)
            assert begun.attempts == expected
            await invocations.settle(
                "t1",
                1,
                claim_token=claimed.claim_token,
                expected_revision=begun.revision,
                status=InvocationStatus.RETRYING,
                outcome=HandlerCallOutcome(DeliveryDisposition.NOT_APPLIED, "pre_send_refusal"),
            )
        # Third send: consumed, then the worker dies without settling.
        await _claim_and_begin(invocations, identity)
        assert (await invocations.get("t1", 1)).attempts == 3
        # Lease lapse, takeover, one more begin attempt: refused at the cap.
        raw = await invocations.get("t1", 1)
        assert raw is not None
        expired = raw.__class__(**{**raw.__dict__, "lease_expires_at": 0.0})
        await invocations.save(expired)
        exhausted = await invocations.claim("t1", 1, delivery=identity)
        assert exhausted is not None  # a claim may still settle the receipt...
        with pytest.raises(DeliveryAttemptLimitReached):
            await invocations.begin_dispatch(
                "t1",
                1,
                claim_token=exhausted.claim_token,
                expected_revision=exhausted.revision,
                delivery=identity,
            )

    async def test_stale_cas_never_settles(self, invocations):
        identity = _identity()
        claimed, _begun = await _claim_and_begin(invocations, identity)
        stale = await invocations.settle(
            "t1",
            1,
            claim_token=claimed.claim_token,
            expected_revision=claimed.revision,  # the begin bumped it
            status=InvocationStatus.SUCCESS,
            outcome=HandlerCallOutcome(DeliveryDisposition.ACKNOWLEDGED),
        )
        assert stale is None
        current = await invocations.get("t1", 1)
        assert current is not None
        assert current.status is InvocationStatus.PENDING  # nothing changed

    async def test_a_delayed_old_sender_cannot_settle_after_takeover(self, invocations):
        """The old sender stalled mid-dispatch; its lease lapsed, a new worker
        took over — the old owner's late settlement is a no-op."""
        identity = _identity()
        first, begun = await _claim_and_begin(invocations, identity)
        # Lease lapse + takeover (simulated expiry write, standing in for time).
        raw = await invocations.get("t1", 1)
        assert raw is not None
        expired = raw.__class__(**{**raw.__dict__, "lease_expires_at": 0.0})
        await invocations.save(expired)
        takeover = await invocations.claim("t1", 1, delivery=identity)
        assert takeover is not None
        assert takeover.uncertain_prior_dispatch  # the marker folded
        # The old sender finally answers with an ack — too late.
        late = await invocations.settle(
            "t1",
            1,
            claim_token=first.claim_token,
            expected_revision=begun.revision,
            status=InvocationStatus.SUCCESS,
            outcome=HandlerCallOutcome(DeliveryDisposition.ACKNOWLEDGED),
        )
        assert late is None
        current = await invocations.get("t1", 1)
        assert current is not None
        assert current.claim_token == takeover.claim_token

    async def test_indeterminate_then_not_applied_stays_unknown_on_exhaustion(self, invocations):
        identity = _identity()
        claimed, begun = await _claim_and_begin(invocations, identity)
        settled = await invocations.settle(
            "t1",
            1,
            claim_token=claimed.claim_token,
            expected_revision=begun.revision,
            status=InvocationStatus.RETRYING,
            outcome=HandlerCallOutcome(DeliveryDisposition.INDETERMINATE, "conn_lost"),
        )
        assert settled is not None and settled.uncertain_prior_dispatch
        # A later proven not-applied call never clears the uncertainty, and
        # FAILED is refused while it exists.
        second, begun2 = await _claim_and_begin(invocations, identity)
        assert second.claim_token != claimed.claim_token
        with pytest.raises(ValueError):
            await invocations.settle(
                "t1",
                1,
                claim_token=second.claim_token,
                expected_revision=begun2.revision,
                status=InvocationStatus.FAILED,
                outcome=HandlerCallOutcome(DeliveryDisposition.NOT_APPLIED, "proven_absent"),
            )
        unknown = await invocations.settle(
            "t1",
            1,
            claim_token=second.claim_token,
            expected_revision=begun2.revision,
            status=InvocationStatus.UNKNOWN,
            outcome=HandlerCallOutcome(DeliveryDisposition.NOT_APPLIED, "proven_absent"),
        )
        assert unknown is not None
        assert unknown.uncertain_prior_dispatch  # never cleared
        assert unknown.settled_for_cursor

    async def test_unknown_is_inspectable_and_never_reclaimed(self, invocations):
        identity = _identity()
        claimed, begun = await _claim_and_begin(invocations, identity)
        settled = await invocations.settle(
            "t1",
            1,
            claim_token=claimed.claim_token,
            expected_revision=begun.revision,
            status=InvocationStatus.UNKNOWN,
            outcome=HandlerCallOutcome(DeliveryDisposition.INDETERMINATE, "conn_lost"),
        )
        assert settled is not None
        assert settled.last_error_code == "conn_lost"
        # No automatic claim/replay of a cursor-settled UNKNOWN receipt.
        assert await invocations.claim("t1", 1, delivery=identity) is None

    async def test_malformed_outcomes_classify_indeterminate_never_acknowledged(self, invocations):
        identity = _identity()
        claimed, begun = await _claim_and_begin(invocations, identity)
        malformed = HandlerCallOutcome(DeliveryDisposition.NOT_APPLIED, "Bad Code!")
        with pytest.raises(ValueError):
            await invocations.settle(
                "t1",
                1,
                claim_token=claimed.claim_token,
                expected_revision=begun.revision,
                status=InvocationStatus.SUCCESS,
                outcome=malformed,
            )
        unknown = await invocations.settle(
            "t1",
            1,
            claim_token=claimed.claim_token,
            expected_revision=begun.revision,
            status=InvocationStatus.UNKNOWN,
            outcome=malformed,
        )
        assert unknown is not None
        assert unknown.last_outcome is DeliveryDisposition.INDETERMINATE
        assert unknown.last_error_code == "malformed_outcome"

    async def test_settle_validates_the_evidence_invariants(self, invocations):
        identity = _identity()
        claimed, begun = await _claim_and_begin(invocations, identity)
        token = claimed.claim_token
        revision = begun.revision
        # SUCCESS requires acknowledged evidence.
        with pytest.raises(ValueError):
            await invocations.settle(
                "t1",
                1,
                claim_token=token,
                expected_revision=revision,
                status=InvocationStatus.SUCCESS,
                outcome=HandlerCallOutcome(DeliveryDisposition.NOT_APPLIED, "absent"),
            )
        # FAILED requires an explicit not_applied reason.
        with pytest.raises(ValueError):
            await invocations.settle(
                "t1",
                1,
                claim_token=token,
                expected_revision=revision,
                status=InvocationStatus.FAILED,
                outcome=HandlerCallOutcome(DeliveryDisposition.NOT_APPLIED, ""),
            )
        # An acknowledged outcome can never settle a non-success status.
        with pytest.raises(ValueError):
            await invocations.settle(
                "t1",
                1,
                claim_token=token,
                expected_revision=revision,
                status=InvocationStatus.RETRYING,
                outcome=HandlerCallOutcome(DeliveryDisposition.ACKNOWLEDGED),
            )
        # PENDING is not a settle target at all.
        with pytest.raises(ValueError):
            await invocations.settle(
                "t1",
                1,
                claim_token=token,
                expected_revision=revision,
                status=InvocationStatus.PENDING,
                outcome=HandlerCallOutcome(DeliveryDisposition.NOT_APPLIED, "x_y"),
            )
        # A well-formed uncertainty-bearing RETRYING is allowed here: the
        # frozen identity enrolled an idempotent contract.
        retrying = await invocations.settle(
            "t1",
            1,
            claim_token=token,
            expected_revision=revision,
            status=InvocationStatus.RETRYING,
            outcome=HandlerCallOutcome(DeliveryDisposition.INDETERMINATE, "conn_lost"),
        )
        assert retrying is not None

    async def test_success_settles_never_bypass_begin_dispatch(self, invocations):
        """Acknowledged evidence alone cannot terminal-settle a receipt that
        never began dispatch: zero attempts and no marker would strand the key
        settled-for-cursor with nothing ever sent (#1060 §3)."""
        identity = _identity()
        claimed = await invocations.claim("t1", 1, delivery=identity)
        assert claimed is not None
        with pytest.raises(ValueError):
            await invocations.settle(
                "t1",
                1,
                claim_token=claimed.claim_token,
                expected_revision=claimed.revision,
                status=InvocationStatus.SUCCESS,
                outcome=HandlerCallOutcome(DeliveryDisposition.ACKNOWLEDGED),
            )
        # The rejected settlement changes nothing; the claim still holds.
        current = await invocations.get("t1", 1)
        assert current is not None
        assert current.status is InvocationStatus.PENDING
        assert current.claim_token == claimed.claim_token
        # After the permission step, the same settlement succeeds.
        begun = await invocations.begin_dispatch(
            "t1",
            1,
            claim_token=claimed.claim_token,
            expected_revision=claimed.revision,
            delivery=identity,
        )
        assert begun is not None
        settled = await invocations.settle(
            "t1",
            1,
            claim_token=begun.claim_token,
            expected_revision=begun.revision,
            status=InvocationStatus.SUCCESS,
            outcome=HandlerCallOutcome(DeliveryDisposition.ACKNOWLEDGED),
        )
        assert settled is not None
        assert settled.status is InvocationStatus.SUCCESS
        assert settled.attempts == 1

    async def test_uncertainty_bearing_retrying_needs_a_safe_contract(self, invocations):
        unsafe = _identity(safety=ReplaySafety.UNPROVEN, ref="")
        claimed, begun = await _claim_and_begin(invocations, unsafe)
        with pytest.raises(ValueError):
            await invocations.settle(
                "t1",
                1,
                claim_token=claimed.claim_token,
                expected_revision=begun.revision,
                status=InvocationStatus.RETRYING,
                outcome=HandlerCallOutcome(DeliveryDisposition.INDETERMINATE, "conn_lost"),
            )

    async def test_the_digest_is_deterministic_for_the_exact_body(self, invocations):
        """Digest v1 pins the exact destination and Event body: any change
        is a different delivery identity."""
        event = LoggedEvent(id=1, event_type="a.b", payload={"k": [1, 2]})
        d1 = request_digest_v1("http://h", event)
        assert d1.startswith("v1:")
        assert d1 == request_digest_v1("http://h", LoggedEvent(**{**event.__dict__}))
        assert d1 != request_digest_v1("http://h2", event)
        mutated = LoggedEvent(id=1, event_type="a.b", payload={"k": [2, 1]})
        assert d1 != request_digest_v1("http://h", mutated)

    async def test_a_truly_unattempted_legacy_row_gets_a_key_on_first_claim(self, invocations):
        identity = _identity()
        # Bookkeeping-only row: pending, attempts=0, no lease, no marker.
        await invocations.get_or_create("t1", 1)
        claimed = await invocations.claim("t1", 1, delivery=identity)
        assert claimed is not None
        assert claimed.delivery_key is not None
        assert claimed.handler_url == "http://h"


class TestLegacyRowMigration:
    """§5 fail-closed reclassification, exercised through ensure_schema.

    The reclassification lives in the schema-upgrade path (SQLite) and the
    bootstrap/migration path (PostgreSQL), so these tests seed pre-contract
    rows by hand and re-run the upgrade, exactly as an operator's database
    would cross the 064 boundary.
    """

    BACKENDS: ClassVar[list[str]] = ["sqlite", "postgres"]

    @pytest.fixture(params=BACKENDS)
    async def upgraded_store(self, request):
        if request.param == "sqlite":
            conn = await aiosqlite.connect(":memory:")
            try:
                store = SqliteInvocationStore(conn)
                await store.ensure_schema()
                await conn.execute(
                    "INSERT INTO handler_invocations "
                    "(trigger_id, event_id, status, attempts, last_error, created_at, lease_expires_at) "
                    "VALUES ('t',1,'failed',2,'boom',1.0,0),"
                    "       ('t',2,'success',1,'',1.0,0),"
                    "       ('t',3,'pending',0,'',1.0,0),"
                    "       ('t',4,'retrying',1,'x',1.0,0),"
                    "       ('t',5,'pending',1,'x',1.0,0)"
                )
                await conn.commit()
                await store.ensure_schema()
                await store.ensure_schema()  # idempotent
                yield store
            finally:
                await conn.close()
        else:
            from maistro.events.pg_stores import PgInvocationStore, ensure_event_schema

            pool = await _pg_pool()
            try:
                await pool.execute(
                    "INSERT INTO handler_invocations "
                    "(trigger_id, event_id, status, attempts, last_error, created_at, lease_expires_at) "
                    "VALUES ('t',1,'failed',2,'boom',1.0,0),"
                    "       ('t',2,'success',1,'',1.0,0),"
                    "       ('t',3,'pending',0,'',1.0,0),"
                    "       ('t',4,'retrying',1,'x',1.0,0),"
                    "       ('t',5,'pending',1,'x',1.0,0)"
                )
                await ensure_event_schema(pool)
                await ensure_event_schema(pool)  # idempotent
                yield PgInvocationStore(pool)
            finally:
                await pool.close()

    async def test_legacy_rows_fail_closed(self, upgraded_store):
        expected = {
            1: (InvocationStatus.UNKNOWN, "legacy_failed_unproven", True),
            2: (InvocationStatus.SUCCESS, "", False),  # preserved acknowledgment
            3: (InvocationStatus.PENDING, "", False),  # truly unattempted
            4: (InvocationStatus.UNKNOWN, "legacy_unkeyed_attempt", True),
            5: (InvocationStatus.UNKNOWN, "legacy_unkeyed_attempt", True),
        }
        for event_id, (status, code, uncertain) in expected.items():
            row = await upgraded_store.get("t", event_id)
            assert row is not None, f"row {event_id} vanished"
            assert row.status is status, f"row {event_id}: {row.status}"
            assert row.last_error_code == code, f"row {event_id}: {row.last_error_code}"
            assert row.uncertain_prior_dispatch is uncertain, f"row {event_id} uncertainty"
            assert row.delivery_key is None  # never invented

    async def test_the_unattempted_legacy_row_can_still_be_claimed(self, upgraded_store):
        identity = _identity()
        claimed = await upgraded_store.claim("t", 3, delivery=identity)
        assert claimed is not None
        assert claimed.delivery_key is not None
        assert claimed.handler_url == "http://h"
        assert claimed.revision == 1


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


class TestConsumerCursorStore:
    """The legacy-bridge replay cursor (#1163): a durable position plus a
    claim lease, so a restart resumes near the last settled point and two
    replicas ticking the bridge at once do not both redo the same range.

    This is a resume *optimisation* on top of `InvocationStore`'s idempotency
    guarantee (ADR-082426-82c7: "the occurrence is the claim, not the
    cursor"), not a replacement for it — these tests are about the cursor
    store's own contract in isolation.
    """

    async def test_a_fresh_consumer_starts_at_position_zero(self, cursor_store):
        lease = await cursor_store.claim("c1", holder="h1")
        assert lease is not None
        assert lease.position == 0

    async def test_advance_persists_the_position_for_the_next_claim(self, cursor_store):
        lease = await cursor_store.claim("c1", holder="h1")
        assert await cursor_store.advance("c1", fencing_token=lease.fencing_token, position=42)

        again = await cursor_store.claim("c1", holder="h1")
        assert again is not None
        assert again.position == 42

    async def test_a_second_holder_is_refused_while_the_lease_is_live(self, cursor_store):
        first = await cursor_store.claim("c1", holder="h1")
        assert first is not None
        assert await cursor_store.claim("c1", holder="h2") is None

    async def test_the_same_holder_can_renew_before_expiry(self, cursor_store):
        """A replica ticking repeatedly must not lock itself out."""
        first = await cursor_store.claim("c1", holder="h1")
        assert first is not None
        second = await cursor_store.claim("c1", holder="h1")
        assert second is not None
        assert second.fencing_token == first.fencing_token

    async def test_an_expired_lease_can_be_taken_over(self, cursor_store):
        expired = await cursor_store.claim("c1", holder="h1", lease_seconds=-1.0)
        assert expired is not None

        taken_over = await cursor_store.claim("c1", holder="h2")
        assert taken_over is not None
        assert taken_over.fencing_token != expired.fencing_token

    async def test_a_stale_fencing_token_cannot_advance_the_cursor(self, cursor_store):
        """Once a lease is taken over, the old holder's `advance` must be a
        no-op rather than clobbering the new holder's position."""
        stale = await cursor_store.claim("c1", holder="h1", lease_seconds=-1.0)
        assert stale is not None
        new_holder = await cursor_store.claim("c1", holder="h2")
        assert new_holder is not None
        await cursor_store.advance("c1", fencing_token=new_holder.fencing_token, position=10)

        accepted = await cursor_store.advance("c1", fencing_token=stale.fencing_token, position=999)
        assert accepted is False

        current = await cursor_store.claim("c1", holder="h2")
        assert current is not None
        assert current.position == 10

    async def test_advance_never_moves_the_position_backwards(self, cursor_store):
        """A monotonic write as a second, independent guard against a stale
        or reordered advance regressing the cursor (defence in depth beyond
        the fencing-token check above)."""
        lease = await cursor_store.claim("c1", holder="h1")
        assert lease is not None
        await cursor_store.advance("c1", fencing_token=lease.fencing_token, position=50)

        await cursor_store.advance("c1", fencing_token=lease.fencing_token, position=10)

        again = await cursor_store.claim("c1", holder="h1")
        assert again is not None
        assert again.position == 50

    async def test_different_consumers_do_not_share_a_cursor(self, cursor_store):
        lease_a = await cursor_store.claim("a", holder="h1")
        assert lease_a is not None
        await cursor_store.advance("a", fencing_token=lease_a.fencing_token, position=100)

        lease_b = await cursor_store.claim("b", holder="h1")
        assert lease_b is not None
        assert lease_b.position == 0

    async def test_only_one_of_many_racing_claims_succeeds(self, cursor_store):
        claims = await asyncio.gather(
            *(cursor_store.claim("c1", holder=f"h{i}") for i in range(16))
        )
        winners = [c for c in claims if c is not None]
        assert len(winners) == 1, f"{len(winners)} replicas would have ticked concurrently"
