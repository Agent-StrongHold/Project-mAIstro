"""Coverage for maistro.quota.sqlite_usage_log.SqliteUsageLog against a real
in-memory sqlite3 DB (via aiosqlite) — no mocking needed."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import aiosqlite
import pytest

from maistro.quota.rate_profile import LimitUnit
from maistro.quota.sqlite_usage_log import SqliteUsageLog
from maistro.quota.usage_log import InMemoryUsageLog


class _BlockingExecutemany:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self._calls = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    async def executemany(self, *args: Any, **kwargs: Any) -> Any:
        result = await self._conn.executemany(*args, **kwargs)
        self._calls += 1
        if self._calls == 1:
            self.started.set()
            await self.release.wait()
        return result


class _CommitAfterWriteFailure:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._failed = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    async def commit(self) -> None:
        await self._conn.commit()
        if not self._failed:
            self._failed = True
            raise RuntimeError("commit result lost")


@pytest.fixture
async def persist() -> AsyncIterator[SqliteUsageLog]:
    conn = await aiosqlite.connect(":memory:")
    p = SqliteUsageLog(conn)
    await p.ensure_schema()
    yield p
    await conn.close()


@pytest.mark.asyncio
async def test_snapshot_then_restore_preserves_events(persist: SqliteUsageLog) -> None:
    log = InMemoryUsageLog()
    log.record("groq:kimi-k2", input_tokens=100, output_tokens=20, now=1000.0)
    log.record("groq:kimi-k2", input_tokens=50, output_tokens=10, now=1010.0)
    log.record("cerebras:qwen3", input_tokens=200, images=1, now=1005.0)

    await persist.snapshot(log)
    restored = await persist.restore()

    assert restored.count_since("groq:kimi-k2", 3600, now=1010.0) == 2.0
    assert restored.tokens_since("groq:kimi-k2", 3600, LimitUnit.INPUT_TOKENS, now=1010.0) == 150.0
    assert restored.tokens_since("groq:kimi-k2", 3600, LimitUnit.OUTPUT_TOKENS, now=1010.0) == 30.0
    assert restored.tokens_since("cerebras:qwen3", 3600, LimitUnit.IMAGES, now=1005.0) == 1.0


@pytest.mark.asyncio
async def test_ensure_schema_backfills_identity_for_legacy_rows() -> None:
    conn = await aiosqlite.connect(":memory:")
    await conn.execute(
        """CREATE TABLE usage_events (
            scope_key TEXT NOT NULL,
            timestamp REAL NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            images INTEGER NOT NULL DEFAULT 0,
            cost_usd REAL NOT NULL DEFAULT 0.0
        )"""
    )
    await conn.execute(
        "INSERT INTO usage_events (scope_key, timestamp, input_tokens) VALUES (?, ?, ?)",
        ("groq:kimi-k2", 1000.0, 4),
    )
    await conn.commit()

    persist = SqliteUsageLog(conn)
    await persist.ensure_schema()
    restored = await persist.restore()

    assert restored.count_since("groq:kimi-k2", 3600, now=1000.0) == 1.0
    cursor = await conn.execute("SELECT event_id FROM usage_events")
    row = await cursor.fetchone()
    assert row[0] == "legacy:1"
    await conn.close()


@pytest.mark.asyncio
async def test_restore_gives_identical_cycles_remaining_before_and_after(
    persist: SqliteUsageLog,
) -> None:
    """Restart-simulation: snapshot a log with events, restore into a fresh
    log, and confirm cycles_remaining() gives the same answer before and
    after -- not just that the SQL round-trips."""
    from maistro.quota.rate_profile import (
        LimitWindow,
        ModelRateProfile,
        RateConstraint,
        cycles_remaining,
    )

    profile = ModelRateProfile(
        provider="groq",
        model="kimi-k2",
        constraints=(
            RateConstraint(unit=LimitUnit.REQUESTS, window=LimitWindow.DAY, limit=14_400),
        ),
    )

    log = InMemoryUsageLog()
    for i in range(5):
        log.record("groq:kimi-k2", input_tokens=10, output_tokens=5, now=1000.0 + i)

    before = cycles_remaining(
        profile, log, requests_per_cycle=1.0, tokens_per_cycle=0.0, scope_values={}
    )

    await persist.snapshot(log)
    restored = await persist.restore()

    after = cycles_remaining(
        profile, restored, requests_per_cycle=1.0, tokens_per_cycle=0.0, scope_values={}
    )

    assert before == after


@pytest.mark.asyncio
async def test_same_timestamp_events_have_distinct_durable_identities(
    persist: SqliteUsageLog,
) -> None:
    log = InMemoryUsageLog()
    log.record("groq:kimi-k2", input_tokens=10, now=1000.0)
    log.record("groq:kimi-k2", input_tokens=20, now=1000.0)

    await persist.snapshot(log)
    restored = await persist.restore()

    assert restored.count_since("groq:kimi-k2", 3600, now=1000.0) == 2.0
    assert restored.tokens_since("groq:kimi-k2", 3600, LimitUnit.INPUT_TOKENS, now=1000.0) == 30.0
    cursor = await persist._conn.execute("SELECT COUNT(DISTINCT event_id) FROM usage_events")
    row = await cursor.fetchone()
    assert row[0] == 2


@pytest.mark.asyncio
async def test_overlapping_snapshots_restore_exactly_once(persist: SqliteUsageLog) -> None:
    log = InMemoryUsageLog()
    log.record("groq:kimi-k2", now=1000.0)
    blocking_conn = _BlockingExecutemany(persist._conn)
    persist._conn = blocking_conn  # type: ignore[assignment]

    first = asyncio.create_task(persist.snapshot(log))
    await asyncio.wait_for(blocking_conn.started.wait(), timeout=1.0)
    second = asyncio.create_task(persist.snapshot(log))
    await asyncio.sleep(0)
    blocking_conn.release.set()
    await asyncio.gather(first, second)

    restored = await persist.restore()
    assert restored.count_since("groq:kimi-k2", 3600, now=1000.0) == 1.0
    cursor = await persist._conn.execute("SELECT COUNT(*) FROM usage_events")
    row = await cursor.fetchone()
    assert row[0] == 1


@pytest.mark.asyncio
async def test_commit_success_then_failure_is_safe_to_retry(persist: SqliteUsageLog) -> None:
    log = InMemoryUsageLog()
    log.record("groq:kimi-k2", input_tokens=7, now=1000.0)
    persist._conn = _CommitAfterWriteFailure(persist._conn)  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="commit result lost"):
        await persist.snapshot(log)

    # A fresh persistence object models the next process after the ambiguous
    # commit result; the durable event identity must make its retry harmless.
    persist_after_restart = SqliteUsageLog(persist._conn)
    await persist_after_restart.ensure_schema()
    await persist_after_restart.snapshot(log)

    restored = await persist_after_restart.restore()
    assert restored.count_since("groq:kimi-k2", 3600, now=1000.0) == 1.0
    assert restored.tokens_since("groq:kimi-k2", 3600, LimitUnit.INPUT_TOKENS, now=1000.0) == 7.0


@pytest.mark.asyncio
async def test_snapshot_is_idempotent_across_calls(
    persist: SqliteUsageLog,
) -> None:
    log = InMemoryUsageLog()
    log.record("groq:kimi-k2", input_tokens=10, now=1000.0)
    await persist.snapshot(log)

    log.record("groq:kimi-k2", input_tokens=20, now=1001.0)
    await persist.snapshot(log)

    restored = await persist.restore()
    assert restored.tokens_since("groq:kimi-k2", 3600, LimitUnit.INPUT_TOKENS, now=1001.0) == 30.0


@pytest.mark.asyncio
async def test_restored_events_keep_identity_for_later_snapshot(
    persist: SqliteUsageLog,
) -> None:
    """Simulates a process restart and verifies restored event identities stay
    stable when the restored log is flushed again."""
    log = InMemoryUsageLog()
    log.record("groq:kimi-k2", input_tokens=10, now=1000.0)
    log.record("groq:kimi-k2", input_tokens=20, now=1001.0)
    await persist.snapshot(log)

    # A fresh instance sharing the same underlying connection -- exactly
    # what a restarted process would construct.
    persist_after_restart = SqliteUsageLog(persist._conn)
    restored = await persist_after_restart.restore()
    assert restored.tokens_since("groq:kimi-k2", 3600, LimitUnit.INPUT_TOKENS, now=1001.0) == 30.0

    # No new events recorded -- this must be idempotent, not a duplicate insert.
    await persist_after_restart.snapshot(restored)
    restored_again = await persist_after_restart.restore()
    assert (
        restored_again.tokens_since("groq:kimi-k2", 3600, LimitUnit.INPUT_TOKENS, now=1001.0)
        == 30.0
    )
    assert restored_again.count_since("groq:kimi-k2", 3600, now=1001.0) == 2.0


@pytest.mark.asyncio
async def test_snapshot_survives_pruning_of_the_live_log(persist: SqliteUsageLog) -> None:
    """Events already persisted remain durable even after the live log prunes
    them from its in-memory window."""
    log = InMemoryUsageLog(max_retention_s=10.0)
    log.record("groq:kimi-k2", input_tokens=1, now=1000.0)
    await persist.snapshot(log)

    # This record's own prune call evicts the first event from the LIVE log
    # (it's now older than max_retention_s), but it must already be safely
    # persisted from the prior snapshot call.
    log.record("groq:kimi-k2", input_tokens=2, now=1012.0)
    await persist.snapshot(log)

    restored = await persist.restore()
    assert restored.tokens_since("groq:kimi-k2", 3600, LimitUnit.INPUT_TOKENS, now=1012.0) == 3.0


@pytest.mark.asyncio
async def test_empty_log_snapshot_is_a_no_op(persist: SqliteUsageLog) -> None:
    log = InMemoryUsageLog()
    await persist.snapshot(log)  # must not raise
    restored = await persist.restore()
    assert restored.scope_keys() == ()


@pytest.mark.asyncio
async def test_restore_reproduces_max_retention_pruning(persist: SqliteUsageLog) -> None:
    log = InMemoryUsageLog()
    log.record("groq:kimi-k2", input_tokens=1, now=1000.0)
    log.record("groq:kimi-k2", input_tokens=2, now=1050.0)
    await persist.snapshot(log)

    # A short retention window means restore should prune the older event
    # away exactly as a live log would have, since it replays through the
    # same InMemoryUsageLog.record() path.
    restored = await persist.restore(max_retention_s=30.0)
    assert restored.tokens_since("groq:kimi-k2", 3600, LimitUnit.INPUT_TOKENS, now=1050.0) == 2.0
