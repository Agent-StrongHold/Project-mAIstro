"""Expired admission claims are purged by the claim path itself (#325).

``purge_expired`` existed on every backend, but nothing in production called
it, so every POST /tasks left a row behind forever. The claim path every
backend shares now drives it: throttled per store, bounded per sweep, and
never able to fail the admission it rides on. These tests go through
``TaskQueue.submit`` — the path POST /tasks takes — and through ``claim`` on
each tier, against real stores.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import aiosqlite
import pytest

from maistro.tasks import idempotency as idem
from maistro.tasks.idempotency import (
    DEFAULT_REPLAY_WINDOW,
    IDEMPOTENCY_PURGE_LIMIT,
    Claimed,
    InMemoryTaskIdempotencyStore,
    PgTaskIdempotencyStore,
    SqliteTaskIdempotencyStore,
    admission_scope_key,
)
from maistro.tasks.models import TaskCreate
from maistro.tasks.queue import TaskQueue

_NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
_EXPIRED = _NOW + DEFAULT_REPLAY_WINDOW + timedelta(seconds=1)


def _scope(key: str) -> str:
    return admission_scope_key(principal="u", workspace_id="w", action="tasks.submit", key=key)


class _Clock:
    """The monotonic clock the purge throttle reads, advanced by hand."""

    def __init__(self) -> None:
        self.value = 1_000.0

    def __call__(self) -> float:
        return self.value


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    fake = _Clock()
    # The module's own `time` binding, not the global module: asyncio's loop
    # clock reads `time.monotonic` too and must keep running.
    monkeypatch.setattr(idem, "time", SimpleNamespace(monotonic=fake))
    return fake


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def store(
    request: pytest.FixtureRequest, tmp_path: Path, pg_pool: Any, clock: _Clock
) -> AsyncIterator[Any]:
    if request.param == "memory":
        yield InMemoryTaskIdempotencyStore()
    elif request.param == "sqlite":
        conn = await aiosqlite.connect(tmp_path / "idempotency.db")
        sqlite_store = SqliteTaskIdempotencyStore(conn)
        await sqlite_store.ensure_schema()
        try:
            yield sqlite_store
        finally:
            await conn.close()
    else:
        if pg_pool is None:
            pytest.skip("MAISTRO_TEST_PG_DSN is not set")
        async with pg_pool.acquire() as conn:
            await conn.execute("DELETE FROM task_idempotency")
        yield PgTaskIdempotencyStore(pg_pool)


async def _seed_expired(store: Any, count: int) -> list[str]:
    """``count`` claims made at ``_NOW`` and admitted, all expired by ``_EXPIRED``.

    Seeded through ``claim`` itself, inside the store's first interval, so no
    purge runs while seeding.
    """
    scopes = [_scope(f"old-{index}") for index in range(count)]
    for scope in scopes:
        claimed = await store.claim(scope, fingerprint="fp", request="{}", now=_NOW)
        assert isinstance(claimed, Claimed)
        # Completing is claimant-fenced (#1176): the outcome lands only with
        # the token the claim itself minted.
        assert (
            await store.complete(scope, token=claimed.token, task_id=f"t-{scope}", run_id=None)
            is True
        )
    return scopes


def _purge_failures() -> float:
    return sum(sample["value"] for sample in idem.task_idempotency_purge_failures_total.collect())


async def _surviving(store: Any, scopes: list[str]) -> list[str]:
    return [scope for scope in scopes if await store.get(scope) is not None]


async def test_a_later_claim_purges_expired_claims(store: Any, clock: _Clock) -> None:
    old = await _seed_expired(store, 3)
    clock.value += idem.IDEMPOTENCY_PURGE_INTERVAL_SECONDS

    fresh = _scope("fresh")
    assert isinstance(
        await store.claim(fresh, fingerprint="fp", request="{}", now=_EXPIRED), Claimed
    )

    assert await _surviving(store, old) == []
    assert await store.get(fresh) is not None


async def test_the_purge_is_bounded_by_its_limit(
    store: Any, clock: _Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(idem, "IDEMPOTENCY_PURGE_LIMIT", 2)
    old = await _seed_expired(store, 5)
    clock.value += idem.IDEMPOTENCY_PURGE_INTERVAL_SECONDS

    await store.claim(_scope("fresh"), fingerprint="fp", request="{}", now=_EXPIRED)

    assert len(await _surviving(store, old)) == 3


async def test_a_claim_inside_the_interval_does_not_purge_again(store: Any, clock: _Clock) -> None:
    old = await _seed_expired(store, 2)
    clock.value += idem.IDEMPOTENCY_PURGE_INTERVAL_SECONDS
    await store.claim(_scope("first"), fingerprint="fp", request="{}", now=_EXPIRED)
    assert await _surviving(store, old) == []

    # Expired by the next claim's clock, but the throttle has not reopened.
    newer = [_scope("newer")]
    newer_claim = await store.claim(newer[0], fingerprint="fp", request="{}", now=_EXPIRED)
    assert isinstance(newer_claim, Claimed)
    await store.complete(newer[0], token=newer_claim.token, task_id="t-newer", run_id=None)
    clock.value += idem.IDEMPOTENCY_PURGE_INTERVAL_SECONDS - 1
    later = _EXPIRED + DEFAULT_REPLAY_WINDOW + timedelta(seconds=1)
    await store.claim(_scope("second"), fingerprint="fp", request="{}", now=later)
    assert await _surviving(store, newer) == newer

    clock.value += 1
    await store.claim(_scope("third"), fingerprint="fp", request="{}", now=later)
    assert await _surviving(store, newer) == []


async def test_a_failing_purge_never_fails_the_claim(
    store: Any, clock: _Clock, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls = 0

    async def broken(*, now: datetime, limit: int = IDEMPOTENCY_PURGE_LIMIT) -> int:
        nonlocal calls
        calls += 1
        raise RuntimeError("database went away")

    monkeypatch.setattr(store, "purge_expired", broken)
    clock.value += idem.IDEMPOTENCY_PURGE_INTERVAL_SECONDS
    failures_before = _purge_failures()

    with caplog.at_level(logging.WARNING, logger=idem.__name__):
        outcome = await store.claim(_scope("k"), fingerprint="fp", request="{}", now=_NOW)

    assert isinstance(outcome, Claimed)
    assert await store.get(_scope("k")) is not None
    assert calls == 1
    assert _purge_failures() == failures_before + 1
    assert "task_idempotency purge failed" in caplog.text

    # The failed attempt still spends the interval: a sick database is not
    # hammered once per admission.
    await store.claim(_scope("k2"), fingerprint="fp", request="{}", now=_NOW)
    assert calls == 1


async def test_a_purge_in_flight_is_not_joined(clock: _Clock) -> None:
    store = InMemoryTaskIdempotencyStore()
    calls = 0

    async def counting(*, now: datetime, limit: int = IDEMPOTENCY_PURGE_LIMIT) -> int:
        nonlocal calls
        calls += 1
        return 0

    store.purge_expired = counting  # type: ignore[method-assign]
    clock.value += idem.IDEMPOTENCY_PURGE_INTERVAL_SECONDS
    async with store._purge_lock:
        await store.claim(_scope("k"), fingerprint="fp", request="{}", now=_NOW)
    assert calls == 0

    await store.claim(_scope("k2"), fingerprint="fp", request="{}", now=_NOW)
    assert calls == 1


async def test_a_new_store_waits_one_interval_before_its_first_purge(
    store: Any, clock: _Clock
) -> None:
    old = await _seed_expired(store, 1)
    clock.value += idem.IDEMPOTENCY_PURGE_INTERVAL_SECONDS - 1

    await store.claim(_scope("fresh"), fingerprint="fp", request="{}", now=_EXPIRED)

    assert await _surviving(store, old) == old


async def test_post_tasks_admission_bounds_the_table(clock: _Clock) -> None:
    """The shipped path: ``TaskQueue`` with the container's claim store, no
    purge wired anywhere else, still deletes an expired claim."""
    store = InMemoryTaskIdempotencyStore()
    stale = await _seed_expired(store, 1)
    clock.value += idem.IDEMPOTENCY_PURGE_INTERVAL_SECONDS
    queue = TaskQueue(idempotency_store=store)

    await queue.submit(TaskCreate(description="Fix the parser"), user_id="alice")

    # The queue claims at the wall clock, years past the seeded window.
    assert await _surviving(store, stale) == []


async def test_a_full_batch_keeps_purging_until_the_backlog_drains(
    store: Any, clock: _Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A batch that hits its limit means a backlog: the next claim sweeps again
    instead of waiting out the interval, so deletion outpaces insertion."""
    monkeypatch.setattr(idem, "IDEMPOTENCY_PURGE_LIMIT", 2)
    old = await _seed_expired(store, 5)
    clock.value += idem.IDEMPOTENCY_PURGE_INTERVAL_SECONDS

    await store.claim(_scope("a"), fingerprint="fp", request="{}", now=_EXPIRED)
    assert len(await _surviving(store, old)) == 3
    await store.claim(_scope("b"), fingerprint="fp", request="{}", now=_EXPIRED)
    assert len(await _surviving(store, old)) == 1
    claim_c = await store.claim(_scope("c"), fingerprint="fp", request="{}", now=_EXPIRED)
    assert isinstance(claim_c, Claimed)
    assert await _surviving(store, old) == []

    # The last batch came up short, so the throttle is back in force.
    newer = _scope("newer")
    await store.complete(_scope("c"), token=claim_c.token, task_id="t-c", run_id=None)
    later = _EXPIRED + DEFAULT_REPLAY_WINDOW + timedelta(seconds=1)
    await store.claim(newer, fingerprint="fp", request="{}", now=later)
    assert await store.get(_scope("c")) is not None


async def test_a_cancelled_purge_strands_no_claim(clock: _Clock) -> None:
    """A request cancelled while its purge runs must not leave behind a pending
    claim nobody owns, which would stall the retry for a whole lease."""
    store = InMemoryTaskIdempotencyStore()
    started = asyncio.Event()

    async def hanging(*, now: datetime, limit: int = IDEMPOTENCY_PURGE_LIMIT) -> int:
        started.set()
        await asyncio.Event().wait()
        return 0

    store.purge_expired = hanging  # type: ignore[method-assign]
    clock.value += idem.IDEMPOTENCY_PURGE_INTERVAL_SECONDS
    claim = asyncio.create_task(store.claim(_scope("k"), fingerprint="fp", request="{}", now=_NOW))
    await started.wait()
    claim.cancel()
    with pytest.raises(asyncio.CancelledError):
        await claim

    assert await store.get(_scope("k")) is None


async def test_pg_purge_spares_a_claim_renewed_under_it(pg_pool: Any, clock: _Clock) -> None:
    """Replicas race: one takes over an expired claim while another's purge has
    already selected it. The purge must re-check expiry on the row it deletes."""
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    async with pg_pool.acquire() as conn:
        await conn.execute("DELETE FROM task_idempotency")
    store = PgTaskIdempotencyStore(pg_pool)
    (scope,) = await _seed_expired(store, 1)
    renewed_until = idem._to_us(_EXPIRED + DEFAULT_REPLAY_WINDOW)

    async with pg_pool.acquire() as taker:
        renewal = taker.transaction()
        await renewal.start()
        await taker.execute(
            "UPDATE task_idempotency SET expires_at = $2, task_id = NULL WHERE scope_key = $1",
            scope,
            renewed_until,
        )
        purge = asyncio.create_task(store.purge_expired(now=_EXPIRED))
        for _ in range(200):
            blocked = await pg_pool.fetchval(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE wait_event_type = 'Lock' AND query LIKE '%DELETE FROM task_idempotency%'"
            )
            if blocked:
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("the purge never blocked on the renewed row")
        await renewal.commit()

    assert await purge == 0
    record = await store.get(scope)
    assert record is not None
    assert record.expires_at_us == renewed_until
