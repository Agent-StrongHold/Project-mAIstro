"""Coverage for maistro.quota.sqlite_usage_log.SqliteUsageLog against a real
in-memory sqlite3 DB (via aiosqlite) — no mocking needed."""

from __future__ import annotations

from collections.abc import AsyncIterator

import aiosqlite
import pytest

from maistro.quota.rate_profile import LimitUnit
from maistro.quota.sqlite_usage_log import SqliteUsageLog
from maistro.quota.usage_log import InMemoryUsageLog


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
async def test_snapshot_is_incremental_not_duplicating_across_calls(
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
async def test_restore_seeds_watermarks_so_a_later_snapshot_does_not_duplicate(
    persist: SqliteUsageLog,
) -> None:
    """Simulates a process restart: snapshot, then restore() into a *fresh*
    SqliteUsageLog instance (as a real restart would), then snapshot the
    restored log again with no new events. Without seeding watermarks in
    restore(), that second snapshot would re-insert every restored event."""
    log = InMemoryUsageLog()
    log.record("groq:kimi-k2", input_tokens=10, now=1000.0)
    log.record("groq:kimi-k2", input_tokens=20, now=1001.0)
    await persist.snapshot(log)

    # A fresh instance sharing the same underlying connection -- exactly
    # what a restarted process would construct.
    persist_after_restart = SqliteUsageLog(persist._conn)
    restored = await persist_after_restart.restore()
    assert restored.tokens_since("groq:kimi-k2", 3600, LimitUnit.INPUT_TOKENS, now=1001.0) == 30.0

    # No new events recorded -- this must be a true no-op, not a re-insert.
    await persist_after_restart.snapshot(restored)
    restored_again = await persist_after_restart.restore()
    assert (
        restored_again.tokens_since("groq:kimi-k2", 3600, LimitUnit.INPUT_TOKENS, now=1001.0)
        == 30.0
    )
    assert restored_again.count_since("groq:kimi-k2", 3600, now=1001.0) == 2.0


@pytest.mark.asyncio
async def test_snapshot_survives_pruning_of_the_live_log(persist: SqliteUsageLog) -> None:
    """A count-based watermark would break here: pruning shifts the deque's
    indices between snapshot calls, so the watermark must be timestamp-based."""
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
