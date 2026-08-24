"""The policy object and the sweeper that rides on admission (#131).

The store's `purge_expired_runs` is proved across all three backends in
`test_retention_conformance`. This is the layer above: what deadline a Run gets,
and when a sweep actually happens. Both matter independently — a correct purge
that never runs is the defect `SqliteSessionStore.purge_expired` was written to
fix, and this is the same shape.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from maistro.runs.retention import (
    DEFAULT_CHAT_RETENTION_SECONDS,
    UNBOUNDED_RETENTION,
    RetentionPolicy,
    RunRetentionSweeper,
)

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


class SpyStore:
    """Just enough RunStore to watch the sweeper."""

    def __init__(self, *, purged: int = 0, fail_with: Exception | None = None) -> None:
        self.calls: list[tuple[datetime | None, int]] = []
        self._purged = purged
        self._fail_with = fail_with

    async def purge_expired_runs(self, *, now: datetime | None = None, limit: int = 500) -> int:
        self.calls.append((now, limit))
        if self._fail_with is not None:
            raise self._fail_with
        return self._purged


class SlowStore(SpyStore):
    def __init__(self, gate: asyncio.Event) -> None:
        super().__init__()
        self._gate = gate

    async def purge_expired_runs(self, *, now: datetime | None = None, limit: int = 500) -> int:
        self.calls.append((now, limit))
        await self._gate.wait()
        return 0


# ── the policy ────────────────────────────────────────────────────


def test_the_default_ttl_is_bounded() -> None:
    policy = RetentionPolicy()

    assert policy.bounded
    assert policy.ttl_seconds == DEFAULT_CHAT_RETENTION_SECONDS


def test_a_deadline_is_the_ttl_after_now() -> None:
    policy = RetentionPolicy(ttl_seconds=3600)

    assert policy.deadline(now=NOW) == NOW + timedelta(hours=1)


def test_no_ttl_means_no_deadline() -> None:
    """The opt-out. `None` reproduces exactly what every other entry point
    already does, which is why it is expressible at all."""
    assert UNBOUNDED_RETENTION.deadline(now=NOW) is None
    assert not UNBOUNDED_RETENTION.bounded


def test_a_deadline_defaults_to_the_real_clock() -> None:
    before = datetime.now(UTC)
    deadline = RetentionPolicy(ttl_seconds=60).deadline()
    assert deadline is not None
    assert before + timedelta(seconds=59) <= deadline <= datetime.now(UTC) + timedelta(seconds=61)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ttl_seconds": 0},
        {"ttl_seconds": -1},
        {"sweep_interval_seconds": -1.0},
        {"batch_limit": 0},
    ],
)
def test_a_nonsense_policy_is_refused(kwargs: dict[str, object]) -> None:
    """Each of these is a policy that silently does nothing — a zero TTL purges
    live-looking work, a zero batch sweeps nothing. Refused at construction
    rather than discovered in production."""
    with pytest.raises(ValueError):
        RetentionPolicy(**kwargs)  # type: ignore[arg-type]


# ── the sweeper ───────────────────────────────────────────────────


async def test_the_first_sweep_happens_immediately() -> None:
    store = SpyStore(purged=3)
    sweeper = RunRetentionSweeper(store, RetentionPolicy())  # type: ignore[arg-type]

    assert await sweeper.maybe_sweep(now=NOW) == 3
    assert store.calls == [(NOW, RetentionPolicy().batch_limit)]


async def test_a_second_sweep_inside_the_interval_is_skipped() -> None:
    store = SpyStore()
    sweeper = RunRetentionSweeper(store, RetentionPolicy(sweep_interval_seconds=3600))  # type: ignore[arg-type]

    await sweeper.maybe_sweep(now=NOW)
    await sweeper.maybe_sweep(now=NOW)

    assert len(store.calls) == 1


async def test_a_zero_interval_sweeps_every_time() -> None:
    store = SpyStore()
    sweeper = RunRetentionSweeper(store, RetentionPolicy(sweep_interval_seconds=0))  # type: ignore[arg-type]

    await sweeper.maybe_sweep(now=NOW)
    await sweeper.maybe_sweep(now=NOW)

    assert len(store.calls) == 2


async def test_an_unbounded_policy_never_sweeps() -> None:
    """Opting out of the deadline has to opt out of the sweep too, or a
    deployment that wanted its Runs kept would still pay for the scan."""
    store = SpyStore()
    sweeper = RunRetentionSweeper(store, UNBOUNDED_RETENTION)  # type: ignore[arg-type]

    assert await sweeper.maybe_sweep(now=NOW) == 0
    assert await sweeper.sweep_now(now=NOW) == 0
    assert store.calls == []


async def test_concurrent_admissions_produce_one_sweep() -> None:
    """A burst of chat turns must not become a burst of sweeps queued behind
    each other — that turns housekeeping into the bottleneck it was meant to
    prevent."""
    gate = asyncio.Event()
    store = SlowStore(gate)
    sweeper = RunRetentionSweeper(store, RetentionPolicy(sweep_interval_seconds=0))  # type: ignore[arg-type]

    waiters = [asyncio.create_task(sweeper.maybe_sweep(now=NOW)) for _ in range(8)]
    await asyncio.sleep(0)
    gate.set()
    await asyncio.gather(*waiters)

    assert len(store.calls) == 1


async def test_a_failing_sweep_does_not_fail_the_admission() -> None:
    """Retention is housekeeping. A database hiccup during a sweep must never
    be the reason a user's chat turn was refused."""
    store = SpyStore(fail_with=RuntimeError("connection reset"))
    sweeper = RunRetentionSweeper(store, RetentionPolicy())  # type: ignore[arg-type]

    assert await sweeper.maybe_sweep(now=NOW) == 0
    assert isinstance(sweeper.last_error, RuntimeError)


async def test_sweep_now_ignores_the_interval_and_propagates_errors() -> None:
    """The escape hatch for an operator or a test: unconditional, and honest
    about failing."""
    store = SpyStore(fail_with=RuntimeError("boom"))
    sweeper = RunRetentionSweeper(store, RetentionPolicy(sweep_interval_seconds=3600))  # type: ignore[arg-type]

    with pytest.raises(RuntimeError):
        await sweeper.sweep_now(now=NOW)


async def test_a_recovered_sweep_clears_the_recorded_error() -> None:
    store = SpyStore(fail_with=RuntimeError("transient"))
    sweeper = RunRetentionSweeper(store, RetentionPolicy(sweep_interval_seconds=0))  # type: ignore[arg-type]
    await sweeper.maybe_sweep(now=NOW)
    assert sweeper.last_error is not None

    store._fail_with = None
    await sweeper.maybe_sweep(now=NOW)

    assert sweeper.last_error is None


async def test_the_batch_limit_reaches_the_store() -> None:
    store = SpyStore()
    sweeper = RunRetentionSweeper(store, RetentionPolicy(batch_limit=7))  # type: ignore[arg-type]

    await sweeper.maybe_sweep(now=NOW)

    assert store.calls[0][1] == 7
