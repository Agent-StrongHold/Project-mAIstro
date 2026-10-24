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

import os

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
async def pg_pool():
    import asyncpg

    pool = await asyncpg.create_pool(_require_postgres(), min_size=1, max_size=4)
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
        await pg_pool.execute("TRUNCATE handler_invocations, trigger_definitions, event_log")
        container = await wire(_config(), pg_pool=pg_pool)

        appended = await container.durable_event_log.append("task.created", entity_id="e1")
        rows = await pg_pool.fetch("SELECT id, event_type, entity_id FROM event_log")

        assert [(r["id"], r["event_type"], r["entity_id"]) for r in rows] == [
            (appended.id, "task.created", "e1")
        ]

    async def test_wiring_creates_the_schema_it_needs(self, pg_pool, wire):
        """A container wired against a database that has never run migrations
        004 and 036 must still come up: `_wire_pg_durable_events` calls
        `ensure_event_schema` once for all four stores."""
        await pg_pool.execute(
            "DROP TABLE IF EXISTS "
            "handler_invocations, trigger_definitions, event_log, consumer_cursors"
        )
        container = await wire(_config(), pg_pool=pg_pool)

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

    async def test_wiring_creates_the_audit_table_it_needs(self, pg_pool, wire):
        """Wiring must create the schema it needs, for the audit store too.

        The Container wires the PostgreSQL audit store on the pool (#122) and
        runs its schema upgrade on every start. That upgrade used to *alter*
        a table it never created, so a database without the audit migrations
        killed the whole Container on startup with `relation "audit_log" does
        not exist` — before the durable event stores were even reached.
        """
        from maistro.persistence.pg_audit import PgAuditLog
        from maistro.types.security import AuditEntry

        await pg_pool.execute("DROP TABLE IF EXISTS audit_log")
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

    async def test_the_audit_table_is_readable_after_the_wiring(self, pg_pool, wire):
        """The store reads back what it wrote, on the table it just created."""
        from maistro.types.security import AuditEntry

        await pg_pool.execute("DROP TABLE IF EXISTS audit_log")
        container = await wire(_config(), pg_pool=pg_pool)

        await container.audit_log.log(
            AuditEntry(boundary="tool_call", user_id="u2", agent_id="a2", verdict="denied")
        )
        entries = await container.audit_log.get_entries(user_id="u2")

        assert [(e.user_id, e.verdict) for e in entries] == [("u2", "denied")]


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

    async def test_wiring_a_bare_pool_also_creates_the_goal_schema(self, pg_pool, wire):
        """The Container composes Goals on the pool too (#1572), and a Goal
        store that refused a database without migration 063 used to kill the
        whole Container before the event schema existed — every test in this
        file went red on a bare service. The contract is the same one the
        event stores ship: wiring creates the schema it needs, and Goals stay
        on the durable PostgreSQL the pool selected — never in memory, never
        on the SQLite tier."""
        from maistro.goals import GoalRevisionDraft
        from maistro.goals.pg_store import PgGoalStore

        # Put the pool's database back to bare first: earlier tests in this
        # file wired Containers, and wiring now creates the Goal tables.
        await pg_pool.execute(
            "DROP TABLE IF EXISTS "
            "canonical_goal_transitions, canonical_goal_revisions, canonical_goals"
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
