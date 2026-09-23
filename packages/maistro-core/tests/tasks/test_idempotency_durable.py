"""The durable idempotency tiers: SQLite for real, PostgreSQL at its seam.

The issue's durability box says claims must survive process restart and
replica handoff, and the stop condition forbids a process-local cache — so the
claim store's contract is proven against a real SQLite file reopened across a
simulated restart, and against the PostgreSQL store's actual statements via
the repo's fake-asyncpg pattern (`test_pg_strikes.py`). The shared claim flow
(`_ClaimFlow`) is already exercised behaviorally by `test_idempotency.py`; what
these tests own is each backend's SQL actually carrying that flow: the primary
key refusing the second claimant, the guards keeping complete/release honest,
and the takeover guard meaning what `_assess` decided.
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

    assert isinstance(await first.claim(scope, fingerprint="fp", request="{}", now=_NOW), Claimed)
    assert await first.complete(scope, task_id="t1", run_id="r1") is True
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
    assert isinstance(await store_a.claim(scope, fingerprint="fp", request="{}", now=_NOW), Claimed)

    conn_b = await _opened(tmp_path)
    store_b = SqliteTaskIdempotencyStore(conn_b)
    await store_b.ensure_schema()
    # Inside the winner's pending lease: the loser waits rather than minting.
    soon = _NOW + timedelta(seconds=5)
    twin = await store_b.claim(scope, fingerprint="fp", request="{}", now=soon)
    assert isinstance(twin, Pending)
    # Past the lease, the same cross-connection claimant takes the stalled
    # claim over — durability includes the takeover, not just the replay.
    assert isinstance(
        await store_b.claim(scope, fingerprint="fp", request="{}", now=_STALL), Claimed
    )
    await conn_a.close()
    await conn_b.close()


async def test_the_fingerprint_contract_is_durable(tmp_path: Path) -> None:
    scope = _scope("k")
    conn = await _opened(tmp_path)
    store = SqliteTaskIdempotencyStore(conn)
    await store.ensure_schema()
    await store.claim(scope, fingerprint="fp-one", request="{}", now=_NOW)
    await store.complete(scope, task_id="t1", run_id="r1")

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
    await store.claim(fresh_scope, fingerprint="fp", request="{}", now=_NOW + timedelta(hours=24))

    assert await store.purge_expired(now=_NOW + timedelta(hours=1)) == 0
    assert await store.purge_expired(now=_NOW + DEFAULT_REPLAY_WINDOW + timedelta(seconds=1)) == 1
    assert await store.get(old_scope) is None
    assert await store.get(fresh_scope) is not None

    assert await store.release(fresh_scope) is True
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
    await store.claim(scope, fingerprint="fp", request="{}", now=_NOW)
    await store.complete(scope, task_id="t1", run_id="r1")

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
        self._pool.calls.append(Call("execute", sql, args))
        return self._pool.execute_results.pop(0)

    async def fetchrow(self, sql: str, *args: Any) -> FakeRecord | None:
        self._pool.calls.append(Call("fetchrow", sql, args))
        return self._pool.fetchrow_results.pop(0)

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self._pool.calls.append(Call("fetchval", sql, args))
        return self._pool.fetchval_results.pop(0)


class FakePool:
    """`asyncpg.Pool` at the boundary this store actually uses: acquire,
    execute, fetchrow, fetchval. Command tags are queued, not invented."""

    def __init__(self) -> None:
        self.calls: list[Call] = []
        self.execute_results: list[str] = []
        self.fetchrow_results: list[FakeRecord | None] = []
        self.fetchval_results: list[Any] = []

    def acquire(self) -> _Acquire:
        return _Acquire(FakeConnection(self))

    async def fetchval(self, sql: str, *args: Any) -> Any:
        """The pool-level read the wiring probe uses — real pools expose it
        directly, without acquiring."""
        self.calls.append(Call("fetchval", sql, args))
        return self.fetchval_results.pop(0)


class _Acquire:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> FakeConnection:
        return self._conn

    async def __aexit__(self, *exc: Any) -> None:
        return None


def _admitted_row(fingerprint: str = "fp", task_id: str = "t1", run_id: str = "r1") -> FakeRecord:
    return FakeRecord(
        (
            "scope",
            fingerprint,
            "{}",
            task_id,
            run_id,
            int((_NOW - timedelta(minutes=1)).timestamp() * 1_000_000),
            int((_NOW + DEFAULT_REPLAY_WINDOW).timestamp() * 1_000_000),
            int((_NOW + PENDING_LEASE).timestamp() * 1_000_000),
        )
    )


def _pending_row(fingerprint: str = "fp") -> FakeRecord:
    return FakeRecord(
        (
            "scope",
            fingerprint,
            "{}",
            None,
            None,
            int((_NOW - timedelta(minutes=1)).timestamp() * 1_000_000),
            int((_NOW + DEFAULT_REPLAY_WINDOW).timestamp() * 1_000_000),
            int((_NOW + PENDING_LEASE).timestamp() * 1_000_000),
        )
    )


async def test_a_fresh_claim_inserts_with_the_conflict_clause() -> None:
    pool = FakePool()
    pool.execute_results.append("INSERT 0 1")
    store = PgTaskIdempotencyStore(pool)

    outcome = await store.claim(_scope("k"), fingerprint="fp", request="{}", now=_NOW)

    assert isinstance(outcome, Claimed)
    (insert,) = [c for c in pool.calls if c.method == "execute"]
    assert "ON CONFLICT (scope_key) DO NOTHING" in insert.sql
    assert insert.args[0].startswith("u") is False  # scope digest, not a raw key
    assert insert.args[3:] == (
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


async def test_a_conflicted_claim_waits_on_a_pending_row() -> None:
    pool = FakePool()
    pool.execute_results.append("INSERT 0 0")
    pool.fetchrow_results.append(_pending_row())
    store = PgTaskIdempotencyStore(pool)

    # Inside the pending claim's lease, so the answer is wait, not takeover.
    soon = _NOW + timedelta(seconds=5)
    outcome = await store.claim(_scope("k"), fingerprint="fp", request="{}", now=soon)

    assert isinstance(outcome, Pending)


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
    assert "expires_at <= $7" in update.sql
    assert "task_id IS NULL AND lease_expires_at <= $7" in update.sql
    assert update.args[-1] == int(_EXPIRED.timestamp() * 1_000_000)


async def test_complete_and_release_carry_the_pending_guard() -> None:
    pool = FakePool()
    pool.execute_results.extend(["UPDATE 1", "DELETE 1"])
    store = PgTaskIdempotencyStore(pool)

    await store.complete(_scope("k"), task_id="t1", run_id="r1")
    await store.release(_scope("k"))

    update, delete = [c for c in pool.calls if c.method == "execute"]
    assert "task_id IS NULL" in update.sql
    assert "task_id IS NULL" in delete.sql


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


# ── the wiring probe ──────────────────────────────────────────────


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


async def test_the_wire_probes_the_table_before_choosing_postgres() -> None:
    pool = FakePool()
    pool.fetchval_results.append(True)
    store = await wire_task_idempotency(None, pg_pool=pool)
    assert isinstance(store, PgTaskIdempotencyStore)
    (probe,) = pool.calls
    assert probe.method == "fetchval"
    assert "task_idempotency" in probe.args[0]

    unmigrated = FakePool()
    unmigrated.fetchval_results.append(False)
    fallback = await wire_task_idempotency(None, pg_pool=unmigrated)
    assert isinstance(fallback, InMemoryTaskIdempotencyStore)
