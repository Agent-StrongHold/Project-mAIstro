"""maistro-server is the operator for abandoned-Attempt recovery (#232)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from maistro_server.abandoned_attempt_recovery import (
    start_abandoned_attempt_recovery,
    stop_abandoned_attempt_recovery,
    tick_abandoned_attempt_recovery,
)


@pytest.fixture(autouse=True)
async def _cadence_stopped() -> Any:
    await stop_abandoned_attempt_recovery()
    yield
    await stop_abandoned_attempt_recovery()


async def test_a_tick_calls_the_container_sweep() -> None:
    seen: list[int] = []

    class _Container:
        async def recover_abandoned_attempts(self, *, limit: int = 100) -> int:
            seen.append(limit)
            return 3

    assert await tick_abandoned_attempt_recovery(_Container()) == 3
    assert seen == [100]


async def test_a_tick_survives_a_store_failure() -> None:
    class _Container:
        async def recover_abandoned_attempts(self, *, limit: int = 100) -> int:
            raise RuntimeError("database unreachable")

    assert await tick_abandoned_attempt_recovery(_Container()) == 0


async def test_a_non_awaitable_recover_is_ignored() -> None:
    class _Container:
        def recover_abandoned_attempts(self, *, limit: int = 100) -> object:
            return object()

    assert await tick_abandoned_attempt_recovery(_Container()) == 0


async def test_start_is_idempotent_and_stop_joins(monkeypatch: pytest.MonkeyPatch) -> None:
    import maistro_server.abandoned_attempt_recovery as cadence

    monkeypatch.setattr(cadence, "_INTERVAL_S", 0.01)
    hits = 0

    class _Container:
        async def recover_abandoned_attempts(self, *, limit: int = 100) -> int:
            nonlocal hits
            hits += 1
            return 0

    container = _Container()
    start_abandoned_attempt_recovery(container)
    start_abandoned_attempt_recovery(container)

    async def _saw_a_tick() -> bool:
        return hits >= 1

    async def _wait() -> None:
        while not await _saw_a_tick():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(_wait(), timeout=2)
    await stop_abandoned_attempt_recovery()
    settled = hits
    await asyncio.sleep(0.05)
    assert hits == settled
    assert cadence._task is None
