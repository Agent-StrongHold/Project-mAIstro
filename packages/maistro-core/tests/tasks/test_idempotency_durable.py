"""The durable idempotency tiers: SQLite for real, PostgreSQL at its seam.

The issue's durability box says claims must survive process restart and
replica handoff, and the stop condition forbids a process-local cache — so the
claim store's contract is proven against a real SQLite file reopened across a
simulated restart, and against the PostgreSQL store's actual statements via
the repo's fake-asyncpg pattern (`test_pg_strikes.py`). The shared claim flow
(`_ClaimFlow`) is already exercised behaviorally by `test_idempotency.py`;
what these tests own is each backend's SQL actually carrying that flow: the
primary key refusing the second claimant, the claimant-token fences keeping
complete/release/begin honest, the takeover guard meaning what `_assess`
decided, and wiring provisioning the PG table instead of degrading a
configured database to process-local state.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from maistro.tasks.idempotency import (
    DEFAULT_REPLAY_WINDOW,
    PENDING_LEASE,
    Ambiguous,
    Claimed,
    IdempotencyKeyMismatch,
    InMemoryTaskIdempotencyStore,
    Pending,
    PgTaskIdempotencyStore,
    Replayed,
    SqliteTaskIdempotencyStore,
    admission_scope_key,
    wire_task_idempotency,
)
from maistro.testing.postgres import postgres_dsn

_NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
_LATER = _NOW + timedelta(minutes=1)
_STALL = _NOW + PENDING_LEASE + timedelta(seconds=1)
_EXPIRED = _NOW + DEFAULT_REPLAY_WINDOW + timedelta(seconds=1)


def _scope(key: str) -> str:
    return admission_scope_key(principal="u", workspace_id="w", action="tasks.submit", key=key)


# ── SQLite: the homelab tier, against a real file ─────────────────


async def _opened(tmp_path: Path) -> aiosqlite.Connection:
    return await aiosqlite.connect(tmp_path / "idempotency.db")


async def test_a_claim_survives_a_restart(tmp_path: Path) -> None:
    """The issue's durability box: the first process claims and admits, dies;
    the retry arrives at a fresh process over the same file and reconciles to
    the recorded outcome instead of minting again."""
    scope = _scope("k")
    first_conn = await _opened(tmp_path)
    first = SqliteTaskIdempotencyStore(first_conn)
    await first.ensure_schema()

    claimed = await first.claim(scope, fingerprint="fp", request="{}", now=_NOW)
    assert isinstance(claimed, Claimed)
    assert await first.complete(scope, token=claimed.token, task_id="t1", run_id="r1") is True
    await first_conn.close()

    second_conn = await _opened(tmp_path)
    second = SqliteTaskIdempotencyStore(second_conn)
    await second.ensure_schema()
    replay = await second.claim(scope, fingerprint="fp", request="{}", now=_LATER)
    assert isinstance(replay, Replayed)
    assert replay.record.task_id == "t1"
    assert replay.record.run_id == "r1"
    await second_conn.close()


async def test_two_connections_to_one_file_cannot_both_claim(tmp_path: Path) -> None:
    """Replica handoff on SQLite: the primary key is the claim, so the second
    process's INSERT is refused at the file and it falls into the replay
    path."""
    scope = _scope("k")
    conn_a = await _opened(tmp_path)
    store_a = SqliteTaskIdempotencyStore(conn_a)
    await store_a.ensure_schema()
    claimed = await store_a.claim(scope, fingerprint="fp", request="{}", now=_NOW)
    assert isinstance(claimed, Claimed)

    conn_b = await _opened(tmp_path)
    store_b = SqliteTaskIdempotencyStore(conn_b)
    await store_b.ensure_schema()
    # Inside the winner's pending lease: the loser waits rather than minting.
    soon = _NOW + timedelta(seconds=5)
    twin = await store_b.claim(scope, fingerprint="fp", request="{}", now=soon)
    assert isinstance(twin, Pending)
    # Past the lease, the same cross-connection claimant takes the stalled
    # claim over — durability includes the takeover, not just the replay.
    takeover = await store_b.claim(scope, fingerprint="fp", request="{}", now=_STALL)
    assert isinstance(takeover, Claimed)
    # And the first claimant's token is dead across the file boundary: its
    # late outcome cannot stamp the winner's row.
    assert await store_a.complete(scope, token=claimed.token, task_id="x", run_id="y") is False
    assert await store_b.complete(scope, token=takeover.token, task_id="t1", run_id="r1") is True
    await conn_a.close()
    await conn_b.close()


async def test_the_begin_announcement_and_the_ambiguous_window_are_durable(
    tmp_path: Path,
) -> None:
    """The discovery protocol, on real rows: a begun claim past its lease is
    ambiguous across processes, resolvable to a minted Run, or takeable when
    discovery finds none."""
    scope = _scope("k")
    conn = await _opened(tmp_path)
    store = SqliteTaskIdempotencyStore(conn)
    await store.ensure_schema()
    claimed = await store.claim(scope, fingerprint="fp", request="{}", now=_NOW)
    assert isinstance(claimed, Claimed)
    assert await store.begin(scope, token=claimed.token, task_id="t1", now=_NOW) is True

    # Cross-connection, past the lease: ambiguous, not takeover.
    ambiguous = await store.claim(scope, fingerprint="fp", request="{}", now=_STALL)
    assert isinstance(ambiguous, Ambiguous)
    assert ambiguous.record.task_id == "t1"

    # Discovery finds the minted Run: resolution records it; the claim replays.
    assert await store.resolve_run(scope, task_id="t1", run_id="r1") is True
    replay = await store.claim(scope, fingerprint="fp", request="{}", now=_STALL)
    assert isinstance(replay, Replayed)
    assert (replay.record.task_id, replay.record.run_id) == ("t1", "r1")

    # And the no-Run resolution frees a begun claim for the fenced takeover:
    # another corpse announced its receipt and died before minting anything.
    bare_scope = _scope("bare")
    bare = await store.claim(bare_scope, fingerprint="fp", request="{}", now=_NOW)
    assert isinstance(bare, Claimed)
    assert await store.begin(bare_scope, token=bare.token, task_id="t2", now=_NOW) is True
    resolved = await store.take_over_resolved(
        bare_scope, task_id="t2", fingerprint="fp", request="{}", now=_STALL
    )
    assert isinstance(resolved, Claimed)
    await conn.close()


async def test_the_fingerprint_contract_is_durable(tmp_path: Path) -> None:
    scope = _scope("k")
    conn = await _opened(tmp_path)
    store = SqliteTaskIdempotencyStore(conn)
    await store.ensure_schema()
    claimed = await store.claim(scope, fingerprint="fp-one", request="{}", now=_NOW)
    assert isinstance(claimed, Claimed)
    await store.complete(scope, token=claimed.token, task_id="t1", run_id="r1")

    with pytest.raises(IdempotencyKeyMismatch):
        await store.claim(scope, fingerprint="fp-two", request="{}", now=_LATER)
    await conn.close()


async def test_the_window_and_the_takeover_are_durable(tmp_path: Path) -> None:
    """Expiry and lease takeover decided by the stored integers, not by anything
    the restarting process remembers."""
    scope = _scope("k")
    conn = await _opened(tmp_path)
    store = SqliteTaskIdempotencyStore(conn)
    await store.ensure_schema()
    await store.claim(scope, fingerprint="fp", request="{}", now=_NOW)

    # Expired window: same key, same payload, fresh admission.
    assert isinstance(
        await store.claim(scope, fingerprint="fp", request="{}", now=_EXPIRED), Claimed
    )
    # Stalled pending claim: a live claimant again, but this time it never
    # completes; the next submitter takes the claim over once the lease lapses.
    stalled = await store.claim(
        scope, fingerprint="fp", request="{}", now=_EXPIRED + timedelta(minutes=1)
    )
    assert isinstance(stalled, Claimed)
    assert isinstance(
        await store.claim(
            scope,
            fingerprint="fp",
            request="{}",
            now=_EXPIRED + timedelta(minutes=1, seconds=PENDING_LEASE.total_seconds() + 1),
        ),
        Claimed,
    )
    await conn.close()


async def test_purge_and_release_run_against_real_rows(tmp_path: Path) -> None:
    old_scope, fresh_scope = _scope("old"), _scope("new")
    conn = await _opened(tmp_path)
    store = SqliteTaskIdempotencyStore(conn)
    await store.ensure_schema()
    await store.claim(old_scope, fingerprint="fp", request="{}", now=_NOW)
    fresh = await store.claim(
        fresh_scope, fingerprint="fp", request="{}", now=_NOW + timedelta(hours=24)
    )
    assert isinstance(fresh, Claimed)

    assert await store.purge_expired(now=_NOW + timedelta(hours=1)) == 0
    assert await store.purge_expired(now=_NOW + DEFAULT_REPLAY_WINDOW + timedelta(seconds=1)) == 1
    assert await store.get(old_scope) is None
    assert await store.get(fresh_scope) is not None

    assert await store.release(fresh_scope, token=fresh.token) is True
    assert await store.get(fresh_scope) is None
    await conn.close()


async def test_ensure_schema_is_idempotent(tmp_path: Path) -> None:
    conn = await _opened(tmp_path)
    store = SqliteTaskIdempotencyStore(conn)
    await store.ensure_schema()
    await store.ensure_schema()
    await conn.close()


async def test_the_takeover_guard_matches_what_the_reader_decided(tmp_path: Path) -> None:
    """A claim that is admitted inside its window must be a replay, never a
    takeover — the write-side guard and the read-side `_assess` agreeing is
    what keeps a retry from minting a second Run."""
    scope = _scope("k")
    conn = await _opened(tmp_path)
    store = SqliteTaskIdempotencyStore(conn)
    await store.ensure_schema()
    claimed = await store.claim(scope, fingerprint="fp", request="{}", now=_NOW)
    assert isinstance(claimed, Claimed)
    await store.complete(scope, token=claimed.token, task_id="t1", run_id="r1")

    # Inside the window: replayed, whatever the lease says.
    replay = await store.claim(
        scope, fingerprint="fp", request="{}", now=_NOW + PENDING_LEASE + timedelta(hours=1)
    )
    assert isinstance(replay, Replayed)
    await conn.close()


# ── PostgreSQL: the statements, at the pool boundary ──────────────


class FakeRecord:
    """Positional row standing in for asyncpg's Record (index access only —
    `_row_of` never names a column)."""

    def __init__(self, values: tuple[Any, ...]) -> None:
        self._values = values

    def __getitem__(self, index: int) -> Any:
        return self._values[index]


class Call:
    def __init__(self, method: str, sql: str, args: tuple[Any, ...]) -> None:
        self.method = method
        self.sql = sql
        self.args = args


class FakeConnection:
    def __init__(self, pool: FakePool) -> None:
        self._pool = pool

    async def execute(self, sql: str, *args: Any) -> str:
        if "CREATE" in sql:
            # DDL routes through the pool's provision behavior (it may refuse).
            return await self._pool._ddl(sql)
        self._pool.calls.append(Call("execute", sql, args))
        return self._pool.execute_results.pop(0)

    async def fetchrow(self, sql: str, *args: Any) -> FakeRecord | None:
        self._pool.calls.append(Call("fetchrow", sql, args))
        return self._pool.fetchrow_results.pop(0)


class FakePool:
    """`asyncpg.Pool` at the boundary this store actually uses: acquire,
    execute, fetchrow. Command tags are queued, not invented."""

    def __init__(self, *, fail_ddl: bool = False) -> None:
        self.calls: list[Call] = []
        self.execute_results: list[str] = []
        self.fetchrow_results: list[FakeRecord | None] = []
        self.fail_ddl = fail_ddl

    def acquire(self) -> _Acquire:
        return _Acquire(FakeConnection(self))

    async def _ddl(self, sql: str) -> str:
        self.calls.append(Call("execute", sql, ()))
        if self.fail_ddl:
            raise RuntimeError("permission denied for table task_idempotency")
        return "CREATE TABLE" if "CREATE TABLE" in sql else "CREATE INDEX"


class _Acquire:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> FakeConnection:
        return self._conn

    async def __aexit__(self, *exc: Any) -> None:
        return None


def _row(
    fingerprint: str = "fp",
    task_id: str | None = "t1",
    run_id: str | None = "r1",
    completed: int = 1,
) -> FakeRecord:
    """One positional row in SELECT order: scope_key first, then the record's
    fields as `_row_of` reads them."""
    return FakeRecord(
        (
            "scope",
            "claim-token-1",
            fingerprint,
            "{}",
            task_id,
            run_id,
            completed,
            int((_NOW - timedelta(minutes=1)).timestamp() * 1_000_000),
            int((_NOW + DEFAULT_REPLAY_WINDOW).timestamp() * 1_000_000),
            int((_NOW + PENDING_LEASE).timestamp() * 1_000_000),
        )
    )


def _admitted_row(fingerprint: str = "fp", task_id: str = "t1", run_id: str = "r1") -> FakeRecord:
    return _row(fingerprint=fingerprint, task_id=task_id, run_id=run_id, completed=1)


def _pending_row(fingerprint: str = "fp") -> FakeRecord:
    return _row(fingerprint=fingerprint, task_id=None, run_id=None, completed=0)


async def test_ensure_schema_provisions_the_table() -> None:
    """A configured pool gets durable claims even before migration 033 runs:
    wiring provisions the table itself, loudly better than the restart-unsafe
    in-memory fallback the previous wiring reached for."""
    pool = FakePool()
    store = PgTaskIdempotencyStore(pool)
    await store.ensure_schema()

    ddl = [c for c in pool.calls if "CREATE" in c.sql]
    assert any("CREATE TABLE IF NOT EXISTS task_idempotency" in c.sql for c in ddl)
    assert any("ix_task_idempotency_expires" in c.sql for c in ddl)
    # The provisioned shape mirrors migration 033, column for column.
    table = next(c.sql for c in ddl if "CREATE TABLE" in c.sql)
    for column in (
        "scope_key TEXT PRIMARY KEY",
        "claim_token TEXT NOT NULL",
        "fingerprint TEXT NOT NULL",
        "request TEXT NOT NULL",
        "task_id TEXT",
        "run_id TEXT",
        "completed_at BIGINT NOT NULL DEFAULT 0",
        "created_at BIGINT NOT NULL",
        "expires_at BIGINT NOT NULL",
        "lease_expires_at BIGINT NOT NULL",
    ):
        assert column in table


async def test_a_fresh_claim_inserts_with_the_conflict_clause() -> None:
    pool = FakePool()
    pool.execute_results.append("INSERT 0 1")
    store = PgTaskIdempotencyStore(pool)

    outcome = await store.claim(_scope("k"), fingerprint="fp", request="{}", now=_NOW)

    assert isinstance(outcome, Claimed)
    (insert,) = [c for c in pool.calls if c.method == "execute"]
    assert "ON CONFLICT (scope_key) DO NOTHING" in insert.sql
    assert insert.args[1] == outcome.token  # the claimant fence is stored
    assert insert.args[2].startswith("u") is False  # scope digest, not a raw key
    assert insert.args[4:] == (
        int(_NOW.timestamp() * 1_000_000),
        int((_NOW + DEFAULT_REPLAY_WINDOW).timestamp() * 1_000_000),
        int((_NOW + PENDING_LEASE).timestamp() * 1_000_000),
    )


async def test_a_conflicted_claim_replays_the_admitted_row() -> None:
    pool = FakePool()
    pool.execute_results.append("INSERT 0 0")
    pool.fetchrow_results.append(_admitted_row())
    store = PgTaskIdempotencyStore(pool)

    outcome = await store.claim(_scope("k"), fingerprint="fp", request="{}", now=_LATER)

    assert isinstance(outcome, Replayed)
    assert outcome.record.task_id == "t1"
    assert outcome.record.claim_token == "claim-token-1"


async def test_a_conflicted_claim_waits_on_a_pending_row() -> None:
    pool = FakePool()
    pool.execute_results.append("INSERT 0 0")
    pool.fetchrow_results.append(_pending_row())
    store = PgTaskIdempotencyStore(pool)

    # Inside the pending claim's lease, so the answer is wait, not takeover.
    soon = _NOW + timedelta(seconds=5)
    outcome = await store.claim(_scope("k"), fingerprint="fp", request="{}", now=soon)

    assert isinstance(outcome, Pending)


async def test_a_begun_lapsed_row_reads_as_ambiguous_at_this_tier_too() -> None:
    pool = FakePool()
    pool.execute_results.append("INSERT 0 0")
    pool.fetchrow_results.append(_row(task_id="t1", run_id=None, completed=0))
    store = PgTaskIdempotencyStore(pool)

    outcome = await store.claim(_scope("k"), fingerprint="fp", request="{}", now=_STALL)

    assert isinstance(outcome, Ambiguous)
    assert outcome.record.task_id == "t1"


async def test_a_mismatched_fingerprint_raises_at_this_tier_too() -> None:
    pool = FakePool()
    pool.execute_results.append("INSERT 0 0")
    pool.fetchrow_results.append(_admitted_row(fingerprint="other"))
    store = PgTaskIdempotencyStore(pool)

    with pytest.raises(IdempotencyKeyMismatch):
        await store.claim(_scope("k"), fingerprint="fp", request="{}", now=_LATER)


async def test_an_expired_row_is_taken_over_through_the_guard() -> None:
    pool = FakePool()
    pool.execute_results.extend(["INSERT 0 0", "UPDATE 1"])
    pool.fetchrow_results.append(_admitted_row())
    store = PgTaskIdempotencyStore(pool)

    outcome = await store.claim(_scope("k"), fingerprint="fp", request="{}", now=_EXPIRED)

    assert isinstance(outcome, Claimed)
    _, update = [c for c in pool.calls if c.method == "execute"]
    assert "expires_at <= $8" in update.sql
    assert "completed_at = 0 AND lease_expires_at <= $8" in update.sql
    assert update.args[-1] == int(_EXPIRED.timestamp() * 1_000_000)


async def test_the_claimant_writes_carry_the_token_fence() -> None:
    """begin/complete/release are the claimant-owned writes: each statement
    must guard on the token and the not-yet-completed row, so a superseded
    claimant's write lands nowhere."""
    pool = FakePool()
    pool.execute_results.extend(["UPDATE 1", "UPDATE 1", "DELETE 1"])
    store = PgTaskIdempotencyStore(pool)

    assert await store.begin(_scope("k"), token="tk", task_id="t1", now=_NOW) is True
    assert await store.complete(_scope("k"), token="tk", task_id="t1", run_id="r1") is True
    assert await store.release(_scope("k"), token="tk") is True

    begin_sql, complete_sql, release_sql = (c.sql for c in pool.calls if c.method == "execute")
    assert "claim_token = $4" in begin_sql
    assert "task_id IS NULL AND completed_at = 0" in begin_sql
    assert "claim_token = $5" in complete_sql
    assert "completed_at = 0" in complete_sql
    assert "claim_token = $2" in release_sql
    assert "completed_at = 0" in release_sql


async def test_resolve_run_and_take_over_resolved_carry_their_guards() -> None:
    """resolve_run writes a discovered fact onto the announced receipt;
    take_over_resolved only lands on the exact begun claim it resolved."""
    pool = FakePool()
    pool.execute_results.extend(["UPDATE 1", "UPDATE 1"])
    pool.fetchrow_results.append(_row(task_id=None, run_id=None, completed=0))
    store = PgTaskIdempotencyStore(pool)

    assert await store.resolve_run(_scope("k"), task_id="t1", run_id="r1") is True
    taken = await store.take_over_resolved(
        _scope("k"), task_id="t1", fingerprint="fp", request="{}", now=_STALL
    )

    assert isinstance(taken, Claimed)
    resolve_sql, take_sql = (c.sql for c in pool.calls if c.method == "execute")
    assert "task_id = $4 AND completed_at = 0" in resolve_sql
    assert "task_id = $8" in take_sql
    assert "completed_at = 0 AND lease_expires_at <= $9" in take_sql


async def test_purge_bounds_its_delete() -> None:
    pool = FakePool()
    pool.execute_results.append("DELETE 3")
    store = PgTaskIdempotencyStore(pool)

    assert await store.purge_expired(now=_EXPIRED, limit=7) == 3
    (purge,) = [c for c in pool.calls if c.method == "execute"]
    assert "WHERE expires_at <= $1" in purge.sql
    assert purge.args == (int(_EXPIRED.timestamp() * 1_000_000), 7)


async def test_the_store_reads_rows_back_positionally() -> None:
    pool = FakePool()
    pool.fetchrow_results.append(_admitted_row(task_id="t9", run_id="r9"))
    store = PgTaskIdempotencyStore(pool)

    record = await store.get(_scope("k"))

    assert record is not None
    assert record.task_id == "t9"
    assert record.run_id == "r9"
    assert record.admitted is True


# ── the wiring ────────────────────────────────────────────────────


async def test_no_backend_wires_the_honest_tier() -> None:
    store = await wire_task_idempotency(None)
    assert isinstance(store, InMemoryTaskIdempotencyStore)


async def test_a_connection_wires_the_sqlite_tier(tmp_path: Path) -> None:
    conn = await aiosqlite.connect(tmp_path / "idempotency.db")
    try:
        store = await wire_task_idempotency(conn)
        assert isinstance(store, SqliteTaskIdempotencyStore)
    finally:
        await conn.close()


async def test_a_configured_pg_pool_gets_durable_claims_not_a_cache(monkeypatch) -> None:
    """The restart-unsafe fallback regression: a pool without the migrated
    table is PROVISIONED at wiring, never silently dropped to in-memory
    state — the issue's stop condition in its exact shape."""
    pool = FakePool()
    store = await wire_task_idempotency(None, pg_pool=pool)
    assert isinstance(store, PgTaskIdempotencyStore)
    ddl = [c for c in pool.calls if "CREATE TABLE IF NOT EXISTS task_idempotency" in c.sql]
    assert ddl, "wiring must provision the claim table on the configured pool"


async def test_an_unprovisionable_pg_pool_degrades_loudly(monkeypatch, caplog) -> None:
    """Only a backend that cannot be provisioned at all (read-only role) falls
    back — and it says so, because a claim store that forgets on restart
    mints a second Run for the first retried submission."""
    import logging

    pool = FakePool(fail_ddl=True)
    with caplog.at_level(logging.WARNING, logger="maistro.tasks.idempotency"):
        store = await wire_task_idempotency(None, pg_pool=pool)
    assert isinstance(store, InMemoryTaskIdempotencyStore)
    assert "task_idempotency_provision_failed" in caplog.text


# ── PostgreSQL for real: the durability box against a live server ──


@pytest.mark.skipif(not postgres_dsn(), reason="set MAISTRO_TEST_PG_DSN")
async def test_the_postgres_tier_reconciles_on_a_real_server(pg_pool) -> None:
    """The fake-pool tests pin the statements; this proves the durability box
    on a real PostgreSQL: the claim, its announcement, the ambiguous window
    and the claimant fence all survive across pools — what a restart or a
    replica handoff actually does. Rows are deleted, never the table: this
    database is shared with the alembic chain, and dropping a migrated table
    under alembic's feet leaves the version stamp pointing at a schema that
    is no longer there."""
    assert pg_pool is not None
    first = PgTaskIdempotencyStore(pg_pool)
    await first.ensure_schema()
    async with pg_pool.acquire() as conn:
        await conn.execute("DELETE FROM task_idempotency")

    claimed = await first.claim(_scope("k"), fingerprint="fp", request="{}", now=_NOW)
    assert isinstance(claimed, Claimed)
    assert await first.begin(_scope("k"), token=claimed.token, task_id="t1", now=_NOW) is True
    # The process dies here: no complete, no release. A fresh pool — a fresh
    # replica — answers the retry.
    second = PgTaskIdempotencyStore(pg_pool)

    ambiguous = await second.claim(_scope("k"), fingerprint="fp", request="{}", now=_STALL)
    assert isinstance(ambiguous, Ambiguous)
    assert ambiguous.record.task_id == "t1"

    # Discovery found the minted Run; the resolution lands on the real row and
    # the replay carries it.
    assert await second.resolve_run(_scope("k"), task_id="t1", run_id="r1") is True
    replay = await second.claim(_scope("k"), fingerprint="fp", request="{}", now=_STALL)
    assert isinstance(replay, Replayed)
    assert (replay.record.task_id, replay.record.run_id) == ("t1", "r1")

    # The corpse's fenced write lands nowhere, even from the first pool.
    assert await first.complete(_scope("k"), token=claimed.token, task_id="x", run_id="y") is False

    # And the no-Run resolution: a fresh begun claim is takeable, once, by
    # exactly the discovery that resolved it.
    bare_scope = _scope("bare")
    bare = await second.claim(bare_scope, fingerprint="fp", request="{}", now=_NOW)
    assert isinstance(bare, Claimed)
    assert await second.begin(bare_scope, token=bare.token, task_id="t2", now=_NOW) is True
    taken = await second.take_over_resolved(
        bare_scope, task_id="t2", fingerprint="fp", request="{}", now=_STALL
    )
    assert isinstance(taken, Claimed)
    assert await second.complete(bare_scope, token=taken.token, task_id="t2", run_id="r2") is True

    async with pg_pool.acquire() as conn:
        await conn.execute("DELETE FROM task_idempotency")
