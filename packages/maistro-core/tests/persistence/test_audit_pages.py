"""Canonical audit pagination: real adapter queries, never list-and-slice."""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import product
from time import perf_counter

import aiosqlite
import pytest

from maistro.persistence.audit_pages import AUDIT_PAGE_INDEXES, MAX_PAGE_SIZE, page_query
from maistro.persistence.pg_audit import PgAuditLog
from maistro.persistence.sqlite_audit import SqliteAuditLog
from maistro.security.sentinel.audit import InMemoryAuditLog
from maistro.types.security import AuditEntry


@pytest.fixture(params=["sqlite", "memory", "postgres"])
async def audit(request, pg_pool):
    if request.param == "postgres":
        if pg_pool is None:
            pytest.skip("MAISTRO_TEST_PG_DSN is not set")
        yield PgAuditLog(pg_pool)
    elif request.param == "memory":
        yield InMemoryAuditLog()
    else:
        async with aiosqlite.connect(":memory:") as conn:
            store = SqliteAuditLog(conn)
            await store.ensure_schema()
            yield store


async def test_pages_stable_with_duplicate_request_ids_and_concurrent_inserts(audit):
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(7):
        await audit.log(AuditEntry(timestamp=stamp, request_id="repeated", detail=str(index)))
    # PostgreSQL owns timestamps at INSERT; pin ties to exercise its row-id key.
    if isinstance(audit, PgAuditLog):
        async with audit._pool.acquire() as conn:
            await conn.execute("UPDATE audit_log SET timestamp = $1", stamp)
    page = await audit.get_page(limit=2)
    seen = [row_id for row_id, _ in page.records]
    assert seen == [7, 6]
    await asyncio.gather(
        *(
            audit.log(AuditEntry(timestamp=stamp + timedelta(days=1), detail="arrival"))
            for _ in range(3)
        )
    )
    while page.next_cursor:
        page = await audit.get_page(limit=2, cursor=page.next_cursor)
        seen.extend(row_id for row_id, _ in page.records)
    assert seen == list(range(7, 0, -1))
    assert len(set(seen)) == 7


async def test_filters_and_scope_precede_limit(audit):
    entry = AuditEntry(org_id="org-a", user_id="alice", boundary="tool", verdict="denied")
    await audit.log(entry)
    for _ in range(3):
        await audit.log(replace(entry, org_id="org-b"))
        await audit.log(replace(entry, user_id="bob"))
        await audit.log(replace(entry, boundary="login"))
        await audit.log(replace(entry, verdict="allowed"))
    page = await audit.get_page(
        org_id="org-a",
        user_id="alice",
        boundary="tool",
        denied=True,
        limit=1,
    )
    assert [row_id for row_id, _ in page.records] == [1]
    assert page.next_cursor is None
    assert (await audit.get_page()).records == []  # explicit system scope
    assert (await audit.get_page(org_id="missing")).records == []
    with pytest.raises(ValueError, match="org_id cannot be None"):
        await audit.get_page(org_id=None)


async def test_maximum_floor_empty_and_malformed_cursor(audit):
    assert (await audit.get_page()).records == []
    for _ in range(MAX_PAGE_SIZE + 2):
        await audit.log(AuditEntry())
    page = await audit.get_page(limit=1_000_000)
    assert len(page.records) == MAX_PAGE_SIZE
    assert page.next_cursor
    assert len((await audit.get_page(limit=-3)).records) == 1
    last = await audit.get_page(cursor=page.next_cursor)
    assert len(last.records) == 2
    assert last.next_cursor is None
    cursor = base64.urlsafe_b64encode(
        json.dumps(["1900-01-01T00:00:00+00:00", 1]).encode()
    ).decode()
    assert (await audit.get_page(cursor=cursor)).records == []
    for malformed in ("invalid", "e30=", "bnVsbA=="):
        with pytest.raises(ValueError, match="malformed audit cursor"):
            await audit.get_page(cursor=malformed)


@pytest.mark.parametrize("corpus_size", [100, 10_000])
async def test_memory_page_reads_only_bounded_records_for_every_filter_shape(corpus_size):
    """Sparse filters and deep ties must seek, not inspect unrelated records."""
    store = InMemoryAuditLog()
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(corpus_size):
        await store.log(
            AuditEntry(
                timestamp=stamp,
                org_id="org-a" if index % 2 else "other",
                user_id="alice" if index % 3 else "bob",
                boundary="tool" if index % 5 else "login",
                verdict="denied" if index % 7 else "allowed",
            )
        )
    records = store._entries

    class ReadBudget(list):
        reads = 0

        def __getitem__(self, key):
            self.reads += len(range(len(self))[key]) if isinstance(key, slice) else 1
            assert self.reads <= 4, "page inspected more than limit + 1 records"
            return super().__getitem__(key)

        def __iter__(self):
            for index in range(len(self)):
                yield self[index]

    store._entries = ReadBudget(records)
    deep = base64.urlsafe_b64encode(
        json.dumps([stamp.isoformat(), corpus_size // 2]).encode()
    ).decode()
    for actor, boundary, denied, cursor in product(
        (None, "alice"), (None, "tool"), (None, False, True), (None, deep)
    ):
        expected = [
            row_id
            for row_id, entry in enumerate(records, start=1)
            if entry.org_id == "org-a"
            and (actor is None or entry.user_id == actor)
            and (boundary is None or entry.boundary == boundary)
            and (denied is None or (entry.verdict == "denied") == denied)
            and (cursor is None or row_id < corpus_size // 2)
        ][::-1]
        store._entries.reads = 0
        page = await store.get_page(
            org_id="org-a",
            user_id=actor,
            boundary=boundary,
            denied=denied,
            cursor=cursor,
            limit=3,
        )
        assert [row_id for row_id, _ in page.records] == expected[:3]
        assert bool(page.next_cursor) == (len(expected) > 3)
    store._entries.reads = 0
    assert (await store.get_page(org_id="absent")).records == []
    assert store._entries.reads == 0


async def test_memory_out_of_order_appends_preserve_cursor_and_filter_indexes():
    store = InMemoryAuditLog()
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    for day in (3, 1, 2):
        await store.log(AuditEntry(timestamp=stamp + timedelta(days=day), user_id="alice"))
    first = await store.get_page(user_id="alice", limit=1)
    assert [row_id for row_id, _ in first.records] == [1]
    await asyncio.gather(
        store.log(AuditEntry(timestamp=stamp + timedelta(days=4), user_id="alice")),
        store.log(AuditEntry(timestamp=stamp, user_id="alice")),
        store.log(AuditEntry(timestamp=stamp, user_id="bob")),
    )
    rest = await store.get_page(user_id="alice", cursor=first.next_cursor)
    assert [row_id for row_id, _ in rest.records] == [3, 2, 5]
    assert rest.next_cursor is None
    assert [row_id for row_id, _ in (await store.get_page(user_id="bob")).records] == [6]


async def test_memory_sync_threads_and_async_writes_share_row_identity():
    store = InMemoryAuditLog()
    stamp = datetime(2026, 1, 1, tzinfo=UTC)

    async def write(index):
        entry = AuditEntry(timestamp=stamp, detail=str(index), user_id="alice")
        if index % 2:
            await asyncio.to_thread(store.log_sync, entry)
        else:
            await store.log(entry)

    await asyncio.gather(*(write(index) for index in range(500)))
    page = await store.get_page(user_id="alice", limit=200)
    records = list(page.records)
    while page.next_cursor:
        page = await store.get_page(user_id="alice", limit=200, cursor=page.next_cursor)
        records.extend(page.records)
    assert [row_id for row_id, _ in records] == list(range(500, 0, -1))
    assert {entry.detail for _, entry in records} == {str(index) for index in range(500)}


async def test_sqlite_million_row_filter_shapes_and_deep_ties():
    """Deterministic VM-work bound on the actual canonical production query."""
    async with aiosqlite.connect(":memory:") as conn:
        store = SqliteAuditLog(conn)
        await store.ensure_schema()
        started = perf_counter()
        await conn.execute("""
            WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<1000000)
            INSERT INTO audit_log (timestamp, org_id, user_id, boundary, verdict)
            SELECT '2026-01-01T00:00:00+00:00',
                   CASE WHEN x % 2 = 0 THEN '' ELSE 'other' END,
                   CASE WHEN x % 3 = 0 THEN 'alice' ELSE 'bob' END,
                   CASE WHEN x % 5 = 0 THEN 'tool' ELSE 'login' END,
                   CASE WHEN x % 7 = 0 THEN 'denied' ELSE 'allowed' END
            FROM n
        """)
        await conn.commit()
        load_seconds = perf_counter() - started
        deep = base64.urlsafe_b64encode(
            json.dumps(["2026-01-01T00:00:00+00:00", 500000]).encode()
        ).decode()
        measured = []
        for actor, boundary, denied, cursor in product(
            (None, "alice"),
            (None, "tool"),
            (None, True),
            (None, deep),
        ):
            ticks = 0

            def progress():
                nonlocal ticks
                ticks += 1
                return int(ticks > 100)  # interrupt a corpus scan, not a slow machine

            await conn.set_progress_handler(progress, 100)
            try:
                page = await store.get_page(
                    org_id="",
                    user_id=actor,
                    boundary=boundary,
                    denied=denied,
                    cursor=cursor,
                    limit=50,
                )
            finally:
                await conn.set_progress_handler(None, 0)
            assert len(page.records) == 50
            assert all(entry.org_id == "" for _, entry in page.records)
            assert all(actor is None or entry.user_id == actor for _, entry in page.records)
            assert all(boundary is None or entry.boundary == boundary for _, entry in page.records)
            assert all(denied is None or entry.verdict == "denied" for _, entry in page.records)
            assert cursor is None or all(row_id < 500000 for row_id, _ in page.records)
            measured.append(ticks * 100)
        print(
            f"canonical SQLite: million-row load={load_seconds:.3f}s; max VM work={max(measured)}"
        )
        assert max(measured) < 10_000
        for name in AUDIT_PAGE_INDEXES:
            result = await conn.execute("SELECT name FROM sqlite_master WHERE name = ?", (name,))
            assert await result.fetchone()


async def test_postgres_million_row_query_envelope(pg_pool):
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    store = PgAuditLog(pg_pool)
    async with pg_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO audit_log (timestamp, org_id, user_id, boundary, verdict)
            SELECT '2026-01-01T00:00:00+00:00'::timestamptz,
                   CASE WHEN x % 2 = 0 THEN '' ELSE 'other' END,
                   CASE WHEN x % 3 = 0 THEN 'alice' ELSE 'bob' END,
                   CASE WHEN x % 5 = 0 THEN 'tool' ELSE 'login' END,
                   CASE WHEN x % 7 = 0 THEN 'denied' ELSE 'allowed' END
            FROM generate_series(1, 1000000) AS x
        """)
        await conn.execute("ANALYZE audit_log")
        deep = base64.urlsafe_b64encode(
            json.dumps(["2026-01-01T00:00:00+00:00", 500000]).encode()
        ).decode()
        max_blocks = 0
        for actor, boundary, denied, cursor in product(
            (None, "alice"),
            (None, "tool"),
            (None, True),
            (None, deep),
        ):
            args = {
                "org_id": "",
                "user_id": actor,
                "boundary": boundary,
                "denied": denied,
                "cursor": cursor,
                "limit": 50,
            }
            page = await store.get_page(**args)
            assert len(page.records) == 50
            assert all(entry.org_id == "" for _, entry in page.records)
            sql, params = page_query(**args, postgres=True)
            raw = await conn.fetchval("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, *params)
            plan = (json.loads(raw) if isinstance(raw, str) else raw)[0]["Plan"]
            blocks = plan["Shared Hit Blocks"] + plan["Shared Read Blocks"]
            max_blocks = max(max_blocks, blocks)
            assert blocks < 500, plan  # work bound, independent of runner speed
        print(f"canonical PostgreSQL million-row maximum query blocks: {max_blocks}")


def test_postgres_query_uses_typed_cursor_and_exact_scope_before_limit():
    cursor = base64.urlsafe_b64encode(
        json.dumps(["2026-01-01T00:00:00+00:00", 42]).encode()
    ).decode()
    sql, args = page_query(
        org_id="org-a",
        user_id="alice",
        boundary="tool",
        denied=True,
        limit=999999,
        cursor=cursor,
        postgres=True,
    )
    assert "org_id = $1" in sql
    assert "user_id = $2" in sql
    assert "boundary = $3" in sql
    assert "(verdict = 'denied') = $4" in sql
    assert "(timestamp, id) < ($5, $6)" in sql
    assert sql.endswith("ORDER BY timestamp DESC, id DESC LIMIT $7")
    assert args == ["org-a", "alice", "tool", True, datetime(2026, 1, 1, tzinfo=UTC), 42, 201]
    naive = base64.urlsafe_b64encode(json.dumps(["2026-01-01", 42]).encode()).decode()
    with pytest.raises(ValueError, match="timezone required"):
        page_query(
            org_id="",
            user_id=None,
            boundary=None,
            denied=None,
            limit=50,
            cursor=naive,
            postgres=True,
        )
