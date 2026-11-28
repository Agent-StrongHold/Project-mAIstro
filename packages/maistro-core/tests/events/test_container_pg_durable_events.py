"""A container handed a PostgreSQL pool gets PostgreSQL durable events (#135).

The selection used to be `db_pool is not None`, and `db_pool` is a *SQLite*
connection. So a deployment on PostgreSQL got `InMemoryEventLog`,
`InMemoryTriggerStore` and `InMemoryInvocationStore` — the event log, the
trigger registry and the invocation history all lost on restart, and the
idempotency guarantee that makes a redelivered event safe holding only within
one process.

These tests are about the *selection*, which is why they assert on types and on
one round trip rather than re-testing store behaviour: the behaviour is covered
once, for all three backends, in `test_durable_store_conformance.py`.

`pg_pool` is a parameter rather than something derived from
`config.database_url`: building a pool from a URL is #122's work, and this
container still refuses `postgresql://` outright. What #135 fixes is that a
caller who already held a pool had no way to reach the durable stores at all.
"""

from __future__ import annotations

import asyncio
import os
import time
from types import SimpleNamespace
from typing import Any

import pytest

from maistro.container import create_container
from maistro.events.durable_log import InMemoryEventLog, SqliteEventLog
from maistro.events.invocations import InMemoryInvocationStore, SqliteInvocationStore
from maistro.events.trigger_store import InMemoryTriggerStore, SqliteTriggerStore
from maistro.types import AgentConfig

DATABASE_URL = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")


def _require_postgres() -> str:
    """The URL, or a skip — unless the caller declared a server is guaranteed.

    See `test_durable_store_conformance._require_postgres`. `MAISTRO_REQUIRE_PG_LEGS`
    is set by the `durable-events` CI job, where skipping would leave the job
    green with the wiring never exercised.
    """
    if DATABASE_URL:
        return DATABASE_URL
    if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
        msg = (
            "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_DATABASE_URL is empty: "
            "the container wiring leg cannot run and must not be silently skipped"
        )
        raise RuntimeError(msg)
    pytest.skip("MAISTRO_TEST_DATABASE_URL is unset; wiring a real pool needs a real server")


def _config(url: str = "memory://") -> AgentConfig:
    return AgentConfig(router_api_key="test-key", database_url=url)


class _WallClock:
    """The wall clock the consumer module reads, advanced by hand."""

    def __init__(self) -> None:
        self.now = time.time()

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
async def wire():
    """Build containers and close the SQLite connections they open.

    `_wire_sqlite_backend` opens an `aiosqlite` connection, and aiosqlite runs
    it on a **non-daemon** worker thread. A container built and dropped leaves
    that thread alive, and a live non-daemon thread blocks interpreter shutdown
    — so a suite that builds sqlite-backed containers and never closes them can
    finish every test and then hang on exit, which reads as a stuck CI job
    rather than a leak. Observed while writing these tests.
    """
    built = []

    async def _build(config: AgentConfig, **kwargs):
        container = await create_container(config, **kwargs)
        built.append(container)
        return container

    try:
        yield _build
    finally:
        for container in built:
            await container.aclose()


@pytest.fixture
async def pg_pool(canonical_event_schema: str):
    import asyncpg

    # Canonical Events require the official migration even while this suite
    # still exercises runtime setup for the separate legacy delivery tables.
    pool = await asyncpg.create_pool(
        _require_postgres(),
        min_size=1,
        max_size=4,
        server_settings={"search_path": f"{canonical_event_schema},public"},
    )
    try:
        yield pool
    finally:
        await pool.close()


class TestPoolSelectsThePostgresStores:
    async def test_a_pool_selects_the_postgres_stores(self, pg_pool, wire):
        from maistro.events.pg_stores import PgEventLog, PgInvocationStore, PgTriggerStore

        container = await wire(_config(), pg_pool=pg_pool)

        assert isinstance(container.durable_event_log, PgEventLog)
        assert isinstance(container.trigger_store, PgTriggerStore)
        assert isinstance(container.handler_invocation_store, PgInvocationStore)

    async def test_the_wired_stores_reach_the_server(self, pg_pool, wire):
        """Types alone would pass against a store holding a dead pool."""
        container = await wire(_config(), pg_pool=pg_pool)

        appended = await container.durable_event_log.append("task.created", entity_id="e1")
        rows = await pg_pool.fetch("SELECT id, event_type, entity_id FROM event_log")

        assert [(r["id"], r["event_type"], r["entity_id"]) for r in rows] == [
            (appended.id, "task.created", "e1")
        ]

    async def test_wiring_creates_the_schema_it_needs(self, pg_pool, wire):
        """Legacy delivery setup remains unchanged by the canonical Event cut.

        Revision 030 is already applied by the pool fixture. The separate
        legacy delivery tables still use `_wire_pg_durable_events`' runtime
        setup until their own migration-authority cut is completed.
        """
        legacy_tables = [
            "handler_invocations",
            "trigger_definitions",
            "event_log",
            "consumer_cursors",
        ]
        catalogue_query = (
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = current_schema() AND tablename = ANY($1::text[])"
        )
        assert not await pg_pool.fetch(catalogue_query, legacy_tables)
        container = await wire(_config(), pg_pool=pg_pool)
        assert {
            row["tablename"] for row in await pg_pool.fetch(catalogue_query, legacy_tables)
        } == set(legacy_tables)

        await container.handler_invocation_store.get_or_create("t1", 1)
        assert len(await container.handler_invocation_store.list_for_event(1)) == 1

    async def test_the_pool_selects_the_canonical_event_publisher_store(self, pg_pool, wire):
        """#1133 on PostgreSQL: recovery dispositions publish through the exact
        backend-selected canonical EventStore, never a second authority.

        `CanonicalEventPublisher` is a delivery wrapper only, so its store
        must be the very object injected into the governed effect context,
        and that object must be the durable PostgreSQL store.
        """
        from maistro.events.pg_envelope import PgEventStore
        from maistro.events.publisher import CanonicalEventPublisher

        container = await wire(_config(), pg_pool=pg_pool)

        publisher = container.canonical_event_publisher
        assert isinstance(publisher, CanonicalEventPublisher)
        assert isinstance(publisher.store, PgEventStore)
        assert publisher.store is container.capability_effects.event_store

        # The wrapper delegates to the durable store: an event published through
        # it reaches the server with the Workspace sequence only the store can
        # assign. A fresh workspace makes the expected sequence independent of
        # any other test that has run against this server.
        from uuid import uuid4

        from maistro.events.envelope import EventEnvelope

        workspace = f"ws-recovery-{uuid4().hex}"
        published = await publisher.emit(
            EventEnvelope(
                type="run.recovery_disposition",
                workspace_id=workspace,
                run_id="run-1",
            )
        )
        assert published.sequence == 1
        rows = await pg_pool.fetchval(
            "SELECT count(*) FROM canonical_event_log WHERE workspace_id = $1",
            workspace,
        )
        assert rows == 1


class TestTheAuditStoreComesUpToo:
    """The audit store is wired on the same pool, so it fails the same way.

    The `durable-events` job is the only CI job that wires a Container against
    a PostgreSQL database that has never run the migration chain, so this is
    where the audit half of the wiring contract is proved.
    """

    async def test_wiring_creates_the_audit_table_it_needs(
        self, pg_pool, wire, canonical_event_schema: str
    ):
        """Wiring must create the schema it needs, for the audit store too.

        The Container wires the PostgreSQL audit store on the pool (#122) and
        runs its schema upgrade on every start. That upgrade used to *alter*
        a table it never created, so a database without the audit migrations
        killed the whole Container on startup with `relation "audit_log" does
        not exist` — before the durable event stores were even reached.
        """
        from maistro.persistence.pg_audit import PgAuditLog
        from maistro.types.security import AuditEntry

        # The reset must name the fixture's schema explicitly. Unqualified, the
        # name resolves along the pool's search_path past the fresh canonical
        # schema into the shared public one, dropping the migrated table every
        # later suite in this pytest process truncates through tests/conftest.
        await pg_pool.execute(f'DROP TABLE IF EXISTS "{canonical_event_schema}".audit_log')
        container = await wire(_config(), pg_pool=pg_pool)

        assert isinstance(container.audit_log, PgAuditLog)

        await container.audit_log.log(
            AuditEntry(
                boundary="tool_call",
                user_id="u1",
                agent_id="a1",
                tool_name="bash",
                verdict="allowed",
                detail="ok",
                trace_id="t1",
                request_id="r1",
            )
        )
        rows = await pg_pool.fetch(
            "SELECT verdict, user_id, org_id, signing_key_id FROM audit_log WHERE trace_id = $1",
            "t1",
        )
        assert [
            (r["verdict"], r["user_id"], r["org_id"], bool(r["signing_key_id"])) for r in rows
        ] == [("allowed", "u1", "", True)]

        # The table this bootstrap created is never migrated afterwards, so
        # every index the read paths rely on has to be here now. `get_page`
        # names one ordered index per filter shape (audit_pages.page_query).
        from maistro.persistence.audit_pages import AUDIT_PAGE_INDEXES

        present = {
            r["indexname"]
            for r in await pg_pool.fetch(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'audit_log'"
            )
        }
        expected = {
            "audit_log_pkey",
            "ix_audit_log_scope",
            "ix_audit_log_timestamp",
            "ix_audit_log_user",
            "ix_audit_log_agent",
            *AUDIT_PAGE_INDEXES,
        }
        assert expected <= present

    async def test_the_audit_table_is_readable_after_the_wiring(
        self, pg_pool, wire, canonical_event_schema: str
    ):
        """The store reads back what it wrote, on the table it just created."""
        from maistro.types.security import AuditEntry

        # Schema-qualified for the same reason as the test above: an
        # unqualified drop would fall through to the shared public schema.
        await pg_pool.execute(f'DROP TABLE IF EXISTS "{canonical_event_schema}".audit_log')
        container = await wire(_config(), pg_pool=pg_pool)

        await container.audit_log.log(
            AuditEntry(boundary="tool_call", user_id="u2", agent_id="a2", verdict="denied")
        )
        entries = await container.audit_log.get_entries(user_id="u2")

        assert [(e.user_id, e.verdict) for e in entries] == [("u2", "denied")]


class TestTheBindingStoreComesUpToo:
    """The Binding authority is wired on the same pool, so it fails the same way.

    Container boot registers the default model.chat Binding through
    ``capability_effects.bindings.put``, and ``PgBindingStore.put`` reads the
    revocation tombstone (#1133) before it inserts. On a database that has
    never run the migrations that read raised ``UndefinedTableError`` on
    ``capability_binding_revocations`` and killed the whole Container before
    the durable event stores were even reached (durable-events CI leg, #1084
    repair): wiring must create the schema the boot registration needs.
    """

    async def test_wiring_creates_the_binding_tables_it_needs(self, pg_pool, wire):
        from maistro.capabilities.binding import Binding
        from maistro.capabilities.binding_store import PgBindingStore

        await pg_pool.execute(
            "DROP TABLE IF EXISTS capability_bindings, capability_binding_revocations"
        )
        container = await wire(_config(), pg_pool=pg_pool)

        assert isinstance(container.capability_effects.bindings, PgBindingStore)

        # The boot model.chat Binding registration ran during wiring and its
        # row landed in the table ensure_schema created — the exact put that
        # used to die on the missing tombstone table.
        rows = await pg_pool.fetch(
            "SELECT payload_json FROM capability_bindings WHERE capability = 'model.chat'"
        )
        assert len(rows) == 1
        assert Binding.model_validate_json(rows[0]["payload_json"]).capability == "model.chat"

        # The tombstone table itself exists, so a later revoke() cannot be the
        # next query to find its table missing.
        assert await pg_pool.fetchval("SELECT count(*) FROM capability_binding_revocations") == 0


class TestTheOtherTwoBackendsAreUnchanged:
    """#135 must not move the SQLite or in-memory selection it sits in front of."""

    async def test_no_pool_and_no_sqlite_url_stays_in_memory(self, wire):
        container = await wire(_config("memory://"))

        assert isinstance(container.durable_event_log, InMemoryEventLog)
        assert isinstance(container.trigger_store, InMemoryTriggerStore)
        assert isinstance(container.handler_invocation_store, InMemoryInvocationStore)

    async def test_a_sqlite_url_and_no_pool_stays_on_sqlite(self, wire):
        container = await wire(_config("sqlite://"))

        assert isinstance(container.durable_event_log, SqliteEventLog)
        assert isinstance(container.trigger_store, SqliteTriggerStore)
        assert isinstance(container.handler_invocation_store, SqliteInvocationStore)

    async def test_a_pool_wins_over_a_sqlite_connection(self, pg_pool, wire):
        """Both can be set at once — they cover different stores. Preferring
        SQLite would hand a multi-worker deployment the one backend whose
        idempotency guarantee does not cross process boundaries."""
        from maistro.events.pg_stores import PgEventLog

        container = await wire(_config("sqlite://"), pg_pool=pg_pool)

        assert isinstance(container.durable_event_log, PgEventLog)

    async def test_wiring_a_bare_pool_also_creates_the_goal_schema(
        self, pg_pool, wire, canonical_event_schema: str
    ):
        """The Container composes Goals on the pool too (#1572), and a Goal
        store that refused a database without migration 063 used to kill the
        whole Container before the event schema existed — every test in this
        file went red on a bare service. The contract is the same one the
        event stores ship: wiring creates the schema it needs, and Goals stay
        on the durable PostgreSQL the pool selected — never in memory, never
        on the SQLite tier."""
        from maistro.goals import GoalRevisionDraft
        from maistro.goals.pg_store import PgGoalStore

        # Reset to bare inside the fixture's schema: each test starts from one
        # fresh canonical schema, so the qualified drop re-states the premise
        # (wiring, not the fixture, creates the Goal tables) without the
        # unqualified names falling through search_path into the shared public
        # schema and taking out the migrated Goal tables for later suites.
        await pg_pool.execute(
            f"DROP TABLE IF EXISTS "
            f'"{canonical_event_schema}".canonical_goal_transitions, '
            f'"{canonical_event_schema}".canonical_goal_revisions, '
            f'"{canonical_event_schema}".canonical_goals'
        )

        container = await wire(_config(), pg_pool=pg_pool)

        assert isinstance(container.goal_store, PgGoalStore)
        goal = await container.goal_store.create_goal(
            workspace_id="ws-events",
            project_id="prj-events",
            agent_id="agent-1",
            draft=GoalRevisionDraft(desired_state="durable", author="op"),
        )
        read = await container.goal_store.get_goal(goal.goal_id)
        assert read is not None and read.current_revision == 1


class TestTheDurableCursorNeverSkipsALateCommit:
    """#2509, end to end on real PostgreSQL.

    `BIGSERIAL` allocates an id inside the appending transaction, so an
    append that is slow to commit leaves a lower id invisible while a
    higher one is readable. The durable cursor must never persist past
    that hole while the appending transaction can still commit — no
    elapsed-time grace is allowed to decide for it — and after the append
    commits, the ordinary production tick must deliver the late id exactly
    once, alongside the id that settled ahead of it.
    """

    @staticmethod
    def _ids_caller(sink: list[int]):
        async def _caller(trigger: object, event: Any) -> None:
            sink.append(event.id)

        return _caller

    @pytest.mark.parametrize(
        "elapsed_between_ticks",
        [0.0, 86_400.0],
        ids=["ticks-at-once", "a-day-between-ticks"],
    )
    async def test_a_hole_a_live_append_may_still_commit_holds_the_cursor(
        self, pg_pool, wire, monkeypatch, elapsed_between_ticks
    ) -> None:
        """The issue's oracle is two containers ticking *after > grace*. The
        first parameterisation is the oracle as first written — every tick
        within milliseconds of the hole opening, which the pre-fix 60 s grace
        also survived. The second turns the consumer module's own wall clock
        a day forward before every tick: no grace a timer could plausibly
        use is still running, and the cursor must hold all the same, because
        the appending transaction — real, on a second connection — can still
        commit. The lease clocks are untouched; only the module that owns
        `_gap_safe_position` reads the hand-turned one."""
        import asyncpg

        import maistro.container as container_module
        from maistro.events.consumer_cursor import LEGACY_BRIDGE_CONSUMER_ID
        from maistro.events.invocations import ReplaySafety
        from maistro.events.trigger_store import TriggerDefinition

        await pg_pool.execute(
            # RESTART IDENTITY: the hole math below reads ids 1..3 off a
            # fresh log, and a plain TRUNCATE leaves the BIGSERIAL sequence
            # at whatever earlier tests in this file consumed.
            "TRUNCATE handler_invocations, trigger_definitions, event_log, "
            "event_replay_cursors, consumer_cursors RESTART IDENTITY"
        )
        clock = _WallClock()
        if elapsed_between_ticks:
            # The module's own `time` binding, not the global module, and
            # `raising=False`: a module with no wall clock is the state this
            # protects; one that re-grew a grace timer reads this clock.
            monkeypatch.setattr(
                container_module,
                "time",
                SimpleNamespace(time=clock, monotonic=clock),
                raising=False,
            )

        def time_passes() -> None:
            clock.advance(elapsed_between_ticks)

        container = await wire(_config(), pg_pool=pg_pool)
        replica = await wire(_config(), pg_pool=pg_pool)
        delivered: list[int] = []
        replica_delivered: list[int] = []
        container.handler_caller = self._ids_caller(delivered)
        replica.handler_caller = self._ids_caller(replica_delivered)
        # A sendable handler_url (the injected caller never dials it): an
        # empty target settles as a pre-send refusal, which would advance
        # the cursor without any dispatch this test is meant to observe.
        await container.trigger_store.add(
            TriggerDefinition(
                trigger_id="t1",
                event_pattern="agent.*",
                handler_url="http://handlers.invalid/agent",
                replay_safety=ReplaySafety.IDEMPOTENT,
                contract_ref="contract-v1",
            )
        )

        await container.durable_event_log.append("agent.created")  # id 1
        holder = await asyncpg.connect(_require_postgres())
        try:
            await holder.execute("BEGIN")
            inflight_id = await holder.fetchval(
                "INSERT INTO event_log (event_type, created_at) "
                "VALUES ('agent.created', 0) RETURNING id"
            )
            assert inflight_id == 2
            await container.durable_event_log.append("agent.created")  # id 3, ahead of 2

            # Two ordinary production ticks while id 2 can still commit —
            # in the second parameterisation, each a day after the last:
            # both settle 3's receipts but the durable cursor — here and on
            # the log's own replay acknowledgement — never passes id 1.
            time_passes()
            assert await container.process_durable_events() == 1
            time_passes()
            assert await container.process_durable_events() == 1
            assert delivered == [1, 3]
            assert (
                await container.durable_event_log.get_replay_cursor(LEGACY_BRIDGE_CONSUMER_ID) == 1
            )

            # Lease transfer to the second replica (wired before the slow
            # append opened: a Container's startup runs schema DDL, which
            # waits on the appending transaction's relation lock — a
            # deployment starts replicas, it does not re-wire per tick). It
            # re-derives the same hold from the durable stores — nothing is
            # skipped by taking over, and the already-settled 3 is deduped,
            # not re-called.
            await pg_pool.execute("UPDATE consumer_cursors SET lease_expires_at = 0")
            time_passes()
            assert await replica.process_durable_events() == 1
            assert replica_delivered == []

            # The slow append commits. The late id must come back — not be
            # lost to a cursor that moved past it while the transaction was
            # merely slow.
            await holder.execute("COMMIT")
        finally:
            await holder.close()

        time_passes()
        assert await replica.process_durable_events() == 3
        assert replica_delivered == [2]
        assert delivered == [1, 3]
        assert await replica.durable_event_log.get_replay_cursor(LEGACY_BRIDGE_CONSUMER_ID) == 3

    async def test_a_rolled_back_hole_is_crossed_on_durable_evidence(self, pg_pool, wire) -> None:
        """The rollback half: bounded forward progress, from durable proof.

        The permanently absent id must not wedge the cursor forever — but
        the tick that crosses it runs after the append's outcome is
        terminally absent (no live sequence holder, still invisible), which
        is database evidence, not a sleep.
        """
        import asyncpg

        from maistro.events.invocations import ReplaySafety
        from maistro.events.trigger_store import TriggerDefinition

        await pg_pool.execute(
            # RESTART IDENTITY: the hole math below reads ids 1..3 off a
            # fresh log, and a plain TRUNCATE leaves the BIGSERIAL sequence
            # at whatever earlier tests in this file consumed.
            "TRUNCATE handler_invocations, trigger_definitions, event_log, "
            "event_replay_cursors, consumer_cursors RESTART IDENTITY"
        )
        container = await wire(_config(), pg_pool=pg_pool)
        delivered: list[int] = []
        container.handler_caller = self._ids_caller(delivered)
        # A sendable handler_url (the injected caller never dials it): an
        # empty target settles as a pre-send refusal, which would advance
        # the cursor without any dispatch this test is meant to observe.
        await container.trigger_store.add(
            TriggerDefinition(
                trigger_id="t1",
                event_pattern="agent.*",
                handler_url="http://handlers.invalid/agent",
                replay_safety=ReplaySafety.IDEMPOTENT,
                contract_ref="contract-v1",
            )
        )

        await container.durable_event_log.append("agent.created")  # id 1
        holder = await asyncpg.connect(_require_postgres())
        try:
            await holder.execute("BEGIN")
            inflight_id = await holder.fetchval(
                "INSERT INTO event_log (event_type, created_at) "
                "VALUES ('agent.created', 0) RETURNING id"
            )
            assert inflight_id == 2
            await container.durable_event_log.append("agent.created")  # id 3

            # The append is live: hold below it.
            assert await container.process_durable_events() == 1

            # The append aborts; its id is terminally absent.
            await holder.execute("ROLLBACK")
        finally:
            await holder.close()

        # One tick after the outcome, on durable evidence: the position
        # crosses the hole to the settled cursor and 3 stays retained.
        assert await container.process_durable_events() == 3
        assert delivered == [1, 3]
        assert await pg_pool.fetchval("SELECT count(*) FROM event_log") == 2


class TestTheReplayAcknowledgementIsFencedThroughTheCursor:
    """#2511, end to end on real PostgreSQL.

    The log's `event_replay_cursors` row carries no fencing token: a tick
    whose `advance` was refused by the canonical cursor (its lease was
    taken over mid-batch) must not publish its rejected position there nor
    report it, even when it processed further than the new holder has —
    and a takeover between an accepted advance and the acknowledgement can
    only ever publish a position the authoritative cursor already accepted.
    """

    @staticmethod
    def _ids_caller(sink: list[int]):
        async def _caller(trigger: object, event: Any) -> None:
            sink.append(event.id)

        return _caller

    async def test_a_lease_takeover_denies_the_old_replica_the_log_acknowledgement(
        self, pg_pool, wire
    ) -> None:
        """Two replicas on two independent pools over one server. Replica A
        pauses mid-batch inside its handler; its lease lapses and replica B
        takes the cursor over; A resumes, settles all three events, and
        tries to advance past B — the advance is refused, and A must
        acknowledge nothing on the log and claim no progress.
        """
        import asyncpg

        from maistro.events.consumer_cursor import LEGACY_BRIDGE_CONSUMER_ID
        from maistro.events.invocations import ReplaySafety
        from maistro.events.trigger_store import TriggerDefinition

        second_pool = await asyncpg.create_pool(_require_postgres(), min_size=1, max_size=4)
        try:
            await pg_pool.execute(
                "TRUNCATE handler_invocations, trigger_definitions, event_log, "
                "event_replay_cursors, consumer_cursors RESTART IDENTITY"
            )
            replica_a = await wire(_config(), pg_pool=pg_pool)
            replica_b = await wire(_config(), pg_pool=second_pool)
            delivered_a: list[int] = []
            delivered_b: list[int] = []
            replica_a.handler_caller = self._ids_caller(delivered_a)
            replica_b.handler_caller = self._ids_caller(delivered_b)
            # A sendable handler_url (the injected caller never dials it): an
            # empty target settles as a pre-send refusal, which would advance
            # the cursor without any dispatch this test is meant to observe.
            await replica_a.trigger_store.add(
                TriggerDefinition(
                    trigger_id="t1",
                    event_pattern="agent.*",
                    handler_url="http://handlers.invalid/agent",
                    replay_safety=ReplaySafety.IDEMPOTENT,
                    contract_ref="contract-v1",
                )
            )

            for _ in range(3):
                await replica_a.durable_event_log.append("agent.created")  # ids 1..3

            a_in_batch = asyncio.Event()
            release_a = asyncio.Event()

            async def pausing_caller(trigger: object, event: Any) -> None:
                if event.id == 1:
                    # The barrier: replica A is parked inside its own batch
                    # while the test takes its lease away.
                    a_in_batch.set()
                    await release_a.wait()
                delivered_a.append(event.id)

            replica_a.handler_caller = pausing_caller
            tick = asyncio.create_task(replica_a.process_durable_events())
            await asyncio.wait_for(a_in_batch.wait(), 10)

            # Force the lease to lapse and replica B (its own pool, its own
            # connection) takes the canonical cursor over — without ticking:
            # B owns the cursor but has advanced nothing. The claim uses B's
            # own holder id so B's production tick later renews it as the
            # same holder.
            await second_pool.execute("UPDATE consumer_cursors SET lease_expires_at = 0")
            lease_b = await replica_b.consumer_cursor_store.claim(
                LEGACY_BRIDGE_CONSUMER_ID, holder=replica_b._durable_events_holder
            )
            assert lease_b is not None
            assert lease_b.position == 0

            release_a.set()
            cursor_a = await asyncio.wait_for(tick, 10)

            # A settled all three events — the receipts are durable — but
            # the canonical cursor refused its write: it must not write the
            # log acknowledgement, report its rejected position, or mirror
            # it, even though it processed further than B has.
            assert delivered_a == [1, 2, 3]
            assert cursor_a == replica_a.durable_event_cursor == 0
            assert (
                await replica_a.consumer_cursor_store.current_position(LEGACY_BRIDGE_CONSUMER_ID)
                == 0
            )
            assert (
                await replica_a.durable_event_log.get_replay_cursor(LEGACY_BRIDGE_CONSUMER_ID) == 0
            )
            assert await second_pool.fetchval("SELECT position FROM consumer_cursors") == 0
            assert await second_pool.fetchval("SELECT count(*) FROM event_replay_cursors") == 0
            assert await second_pool.fetchval("SELECT count(*) FROM handler_invocations") == 3

            # B now ticks under its own lease: A's settled receipts dedupe
            # (no dispatch is repeated), the accepted advance carries the log
            # acknowledgement, and both pools read the same consistent
            # checkpoint back.
            cursor_b = await replica_b.process_durable_events()
            assert delivered_b == []
            assert cursor_b == replica_b.durable_event_cursor == 3
            assert (
                await replica_b.durable_event_log.get_replay_cursor(LEGACY_BRIDGE_CONSUMER_ID) == 3
            )
            assert (
                await replica_a.durable_event_log.get_replay_cursor(LEGACY_BRIDGE_CONSUMER_ID) == 3
            )
            assert (
                await replica_a.consumer_cursor_store.current_position(LEGACY_BRIDGE_CONSUMER_ID)
                == 3
            )
            assert await second_pool.fetchval("SELECT count(*) FROM handler_invocations") == 3
        finally:
            await second_pool.close()

    async def test_a_takeover_between_the_advance_and_the_acknowledgement_publishes_the_authoritative_position(
        self, pg_pool, wire
    ) -> None:
        """Replica B takes the lease over in the window between replica A's
        accepted primary advance and A's log acknowledgement. A acknowledges
        the authoritative cursor — re-read from the store, which B has
        already advanced further — never its own pre-takeover view, so the
        log's replay cursor stays inside what the primary cursor accepted.
        """
        import asyncpg

        from maistro.events.consumer_cursor import LEGACY_BRIDGE_CONSUMER_ID
        from maistro.events.invocations import ReplaySafety
        from maistro.events.trigger_store import TriggerDefinition

        second_pool = await asyncpg.create_pool(_require_postgres(), min_size=1, max_size=4)
        try:
            await pg_pool.execute(
                "TRUNCATE handler_invocations, trigger_definitions, event_log, "
                "event_replay_cursors, consumer_cursors RESTART IDENTITY"
            )
            replica_a = await wire(_config(), pg_pool=pg_pool)
            replica_b = await wire(_config(), pg_pool=second_pool)
            delivered: list[int] = []
            replica_a.handler_caller = self._ids_caller(delivered)
            await replica_a.trigger_store.add(
                TriggerDefinition(
                    trigger_id="t1",
                    event_pattern="agent.*",
                    handler_url="http://handlers.invalid/agent",
                    replay_safety=ReplaySafety.IDEMPOTENT,
                    contract_ref="contract-v1",
                )
            )

            await replica_a.durable_event_log.append("agent.created")
            await replica_a.durable_event_log.append("agent.created")  # ids 1..2

            cursor_store = replica_a.consumer_cursor_store
            holder = replica_a._durable_events_holder

            async def handover() -> None:
                """Runs after replica A's advance is accepted, before its
                acknowledgement: B takes the lease over and advances the
                authoritative cursor further (its own settled tick)."""
                await cursor_store.claim(
                    LEGACY_BRIDGE_CONSUMER_ID, holder=holder, lease_seconds=-1.0
                )
                lease_b = await cursor_store.claim(
                    LEGACY_BRIDGE_CONSUMER_ID, holder=replica_b._durable_events_holder
                )
                assert lease_b is not None
                assert await cursor_store.advance(
                    LEGACY_BRIDGE_CONSUMER_ID,
                    fencing_token=lease_b.fencing_token,
                    position=9,
                )

            class _HandoverAfterAdvance:
                def __init__(self, inner: Any, hook: Any) -> None:
                    self._inner = inner
                    self._hook = hook

                def __getattr__(self, name: str) -> Any:
                    return getattr(self._inner, name)

                async def advance(
                    self, consumer_id: str, *, fencing_token: str, position: int
                ) -> bool:
                    accepted = await self._inner.advance(
                        consumer_id, fencing_token=fencing_token, position=position
                    )
                    if accepted:
                        await self._hook()
                    return accepted

            replica_a.consumer_cursor_store = _HandoverAfterAdvance(cursor_store, handover)  # type: ignore[assignment]
            cursor_a = await replica_a.process_durable_events()
            replica_a.consumer_cursor_store = cursor_store  # type: ignore[assignment]

            # The authoritative cursor (9) is what both replicas report and
            # what the log acknowledges: A's own advance reached only 2, and
            # the unfenced acknowledgement published nothing beyond what the
            # primary cursor explicitly accepted.
            assert delivered == [1, 2]
            assert cursor_a == replica_a.durable_event_cursor == 9
            assert await second_pool.fetchval("SELECT position FROM consumer_cursors") == 9
            assert await second_pool.fetchval("SELECT event_id FROM event_replay_cursors") == 9
            assert (
                await replica_a.durable_event_log.get_replay_cursor(LEGACY_BRIDGE_CONSUMER_ID) == 9
            )

            # The takeover is clean: B renews its own lease and continues
            # from the authoritative position with nothing contradictory to
            # reconcile.
            cursor_b = await replica_b.process_durable_events()
            assert cursor_b == 9
            assert await second_pool.fetchval("SELECT event_id FROM event_replay_cursors") == 9
        finally:
            await second_pool.close()
