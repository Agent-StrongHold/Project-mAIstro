"""Expired admission claims are purged by the claim path itself (#325).

``purge_expired`` existed on every backend, but nothing in production called
it, so every POST /tasks left a row behind forever. The claim path every
backend shares now drives it: throttled per store, bounded per sweep, and
never able to fail the admission it rides on. These tests go through
``TaskQueue.submit`` — the path POST /tasks takes — and through ``claim`` on
each tier, against real stores.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
    monkeypatch.setattr(idem.time, "monotonic", fake)
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
        assert isinstance(
            await store.claim(scope, fingerprint="fp", request="{}", now=_NOW), Claimed
        )
        assert await store.complete(scope, task_id=f"t-{scope}", run_id=None) is True
    return scopes


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
    await store.claim(newer[0], fingerprint="fp", request="{}", now=_EXPIRED)
    await store.complete(newer[0], task_id="t-newer", run_id=None)
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

    with caplog.at_level(logging.WARNING, logger=idem.__name__):
        outcome = await store.claim(_scope("k"), fingerprint="fp", request="{}", now=_NOW)

    assert isinstance(outcome, Claimed)
    assert await store.get(_scope("k")) is not None
    assert calls == 1
    assert store.purge_failures == 1
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
