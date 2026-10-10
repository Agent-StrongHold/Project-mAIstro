"""Real migration/least-privilege proof for the #1135 canonical Event cut.

Only disposable test schemas and a uniquely named NOLOGIN test role are changed.
No production role or database settings are modified. Both existing PostgreSQL
CI jobs run this suite and require its database legs rather than skipping them.
"""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import asyncpg
import pytest

from maistro.events.envelope import EventEnvelope
from maistro.events.pg_envelope import PgEventStore
from maistro.events.wiring import wire_canonical_events


async def test_migrated_store_wires_and_restarts_without_schema_privileges(
    canonical_event_schema: str,
) -> None:
    dsn = os.environ["MAISTRO_TEST_DATABASE_URL"]
    schema = canonical_event_schema
    role = f"canonical_event_dml_{uuid4().hex}"
    admin = await asyncpg.connect(dsn)
    pools = []
    try:
        await admin.execute(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE')
        await admin.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"')
        await admin.execute(f'GRANT SELECT, INSERT ON "{schema}".canonical_event_log TO "{role}"')

        async def setup(conn):
            await conn.execute(f'SET ROLE "{role}"')

        async def pool():
            created = await asyncpg.create_pool(
                dsn,
                min_size=1,
                max_size=4,
                server_settings={"search_path": schema},
                setup=setup,
            )
            pools.append(created)
            return created

        first = await pool()
        assert await first.fetchval("SELECT current_user") == role
        assert not await first.fetchval(
            "SELECT has_schema_privilege(current_user, $1, 'CREATE')", schema
        )
        assert not await first.fetchval(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        )
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await first.execute("CREATE TABLE runtime_ddl_probe (id integer)")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await first.execute(
                "ALTER TABLE canonical_event_log ADD COLUMN runtime_ddl_probe integer"
            )

        publisher = await wire_canonical_events(pg_pool=first)
        event = EventEnvelope(event_id="stable-id", type="run.started", workspace_id="ws")
        persisted = await publisher.emit(event)
        assert persisted.sequence == 1
        await first.close()

        # A fresh pool and another replica see the same authoritative identity.
        restarted, replica = await pool(), await pool()
        left = (await wire_canonical_events(pg_pool=restarted)).store
        right = (await wire_canonical_events(pg_pool=replica)).store
        assert await left.get(event.event_id) == persisted
        retries = await asyncio.gather(left.append(event), right.append(event))
        assert retries == [persisted, persisted]
        appended = await right.append(
            EventEnvelope(event_id="next-id", type="run.finished", workspace_id="ws")
        )
        assert appended.sequence == 2
        assert [row.event_id for row in await left.list_stream(event.stream_id)] == [
            "stable-id",
            "next-id",
        ]
    finally:
        for opened in pools:
            await opened.close()
        await admin.execute(f'DROP OWNED BY "{role}"')
        await admin.execute(f'DROP ROLE "{role}"')
        await admin.close()


@pytest.mark.parametrize("damage", ["missing_table", "missing_column", "missing_unique_key"])
async def test_incompatible_schema_fails_readiness_without_repair(
    canonical_event_schema: str, damage: str
) -> None:
    schema = canonical_event_schema
    pool = await asyncpg.create_pool(
        os.environ["MAISTRO_TEST_DATABASE_URL"],
        min_size=1,
        max_size=1,
        server_settings={"search_path": schema},
    )
    try:
        if damage == "missing_table":
            await pool.execute("DROP TABLE canonical_event_log")
            expected = asyncpg.UndefinedTableError
        elif damage == "missing_column":
            await pool.execute("ALTER TABLE canonical_event_log DROP COLUMN provenance")
            expected = asyncpg.UndefinedColumnError
        else:
            await pool.execute(
                "ALTER TABLE canonical_event_log DROP CONSTRAINT uq_canonical_event_stream_sequence"
            )
            expected = RuntimeError
        # Even an owner capable of repairing the schema must not do so, and
        # supplying an alternate backend cannot turn the failure into fallback.
        with pytest.raises(expected):
            await wire_canonical_events(pg_pool=pool, db_pool=object())
        with pytest.raises(expected):
            await PgEventStore(pool).ensure_schema()
    finally:
        await pool.close()


@pytest.mark.parametrize("column", ["sequence", "timestamp", "payload", "provenance"])
async def test_wrong_column_type_fails_readiness_before_append(
    canonical_event_schema: str, column: str
) -> None:
    pool = await asyncpg.create_pool(
        os.environ["MAISTRO_TEST_DATABASE_URL"],
        min_size=1,
        max_size=1,
        server_settings={"search_path": canonical_event_schema},
    )
    try:
        # The official migration created the table. Change only a consumed
        # type; all names and both unique indexes remain intact.
        await pool.execute(f'ALTER TABLE canonical_event_log ALTER COLUMN "{column}" DROP DEFAULT')
        await pool.execute(
            f'ALTER TABLE canonical_event_log ALTER COLUMN "{column}" TYPE text USING "{column}"::text'
        )
        with pytest.raises(RuntimeError, match=f"incompatible column types: {column}"):
            await wire_canonical_events(pg_pool=pool, db_pool=object())
        assert await pool.fetchval("SELECT count(*) FROM canonical_event_log") == 0
        assert (
            await pool.fetchval(
                "SELECT atttypid::regtype::text FROM pg_attribute "
                "WHERE attrelid = 'canonical_event_log'::regclass AND attname = $1",
                column,
            )
            == "text"
        )
    finally:
        await pool.close()


@pytest.mark.parametrize(
    "privileges", ["select_only", "partial_insert", "column_insert", "column_select"]
)
async def test_preflight_requires_only_insert_privileges_used_by_append(
    canonical_event_schema: str, privileges: str
) -> None:
    dsn = os.environ["MAISTRO_TEST_DATABASE_URL"]
    schema = canonical_event_schema
    role = f"canonical_event_insert_{uuid4().hex}"
    admin = await asyncpg.connect(dsn)
    pool = None
    try:
        await admin.execute(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE')
        await admin.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"')
        # Additive migration columns must not require privileges the store
        # never uses. Derive the fixture's original columns from real 030.
        columns = await admin.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = $1 AND table_name = 'canonical_event_log' "
            "ORDER BY ordinal_position",
            schema,
        )
        assert len(columns) == 19
        if privileges == "column_select":
            selected = ", ".join(f'"{row["column_name"]}"' for row in columns)
            await admin.execute(
                f'GRANT SELECT ({selected}) ON "{schema}".canonical_event_log TO "{role}"'
            )
        else:
            await admin.execute(f'GRANT SELECT ON "{schema}".canonical_event_log TO "{role}"')
        await admin.execute(
            f'ALTER TABLE "{schema}".canonical_event_log ADD COLUMN future_field integer DEFAULT 0'
        )
        if privileges != "select_only":
            granted = columns[:-1] if privileges == "partial_insert" else columns
            names = ", ".join(f'"{row["column_name"]}"' for row in granted)
            await admin.execute(
                f'GRANT INSERT ({names}) ON "{schema}".canonical_event_log TO "{role}"'
            )

        async def setup(conn):
            await conn.execute(f'SET ROLE "{role}"')

        pool = await asyncpg.create_pool(
            dsn,
            min_size=1,
            max_size=1,
            server_settings={"search_path": schema},
            setup=setup,
        )
        assert await pool.fetchval("SELECT current_user") == role
        assert not await pool.fetchval(
            "SELECT has_table_privilege('canonical_event_log', 'INSERT')"
        )
        assert not await pool.fetchval(
            "SELECT has_column_privilege('canonical_event_log', 'future_field', 'INSERT')"
        )
        if privileges == "column_select":
            # The 19 consumed columns are readable, but real get/list/append
            # lookups use SELECT *. Readiness must cover that actual contract.
            assert not await pool.fetchval(
                "SELECT has_column_privilege('canonical_event_log', 'future_field', 'SELECT')"
            )
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await wire_canonical_events(pg_pool=pool, db_pool=object())
            assert await admin.fetchval(f'SELECT count(*) FROM "{schema}".canonical_event_log') == 0
        elif privileges == "column_insert":
            publisher = await wire_canonical_events(pg_pool=pool)
            event = await publisher.emit(
                EventEnvelope(event_id="column-grant", type="run.started", workspace_id="ws")
            )
            assert event.sequence == 1
            assert await publisher.store.get(event.event_id) == event
        else:
            with pytest.raises(RuntimeError, match="requires INSERT privilege"):
                await wire_canonical_events(pg_pool=pool, db_pool=object())
            assert await pool.fetchval("SELECT count(*) FROM canonical_event_log") == 0
    finally:
        if pool is not None:
            await pool.close()
        await admin.execute(f'DROP OWNED BY "{role}"')
        await admin.execute(f'DROP ROLE "{role}"')
        await admin.close()
